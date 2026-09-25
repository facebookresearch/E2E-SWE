/*
 * Shared C-native test harness for the lauf held-out grader.
 *
 * Each test-group binary lives in its own translation unit and is compiled +
 * linked separately, so a compile error in one group only sinks that group —
 * every other group still contributes its passing tests to the aggregate CTRF.
 * Each test runs in its own forked process for crash isolation: a segfault or
 * abort in one test fails only that test, not the whole group.
 *
 * A group binary is invoked as `./bin <path-to-output-fragment>` and writes a
 * JSON array of {"name","status","duration","message"} entries. test.sh
 * concatenates every group's fragment into /logs/verifier/ctrf.json.
 */
#ifndef LAUF_TEST_HARNESS_H
#define LAUF_TEST_HARNESS_H

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef struct
{
    const char* name;
    int         passed;
    char        msg[512];
} Result;

/* Shared-memory pointer used by the child process to record its verdict. */
static Result* cur;

/* FAIL / CHECK format a message into the shared Result and mark it failed.
 * FAIL early-returns from the test function; CHECK only trips on false. */
#define FAIL(...)                                                                                  \
    do                                                                                             \
    {                                                                                              \
        snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__);                                          \
        cur->passed = 0;                                                                           \
        return;                                                                                    \
    } while (0)

#define CHECK(c, ...)                                                                              \
    do                                                                                             \
    {                                                                                              \
        if (!(c))                                                                                  \
            FAIL(__VA_ARGS__);                                                                     \
    } while (0)

typedef struct
{
    const char* name;
    void (*fn)(void);
} TestEntry;

/* JSON-escape a raw C string into `dest`. Escapes ", \, and control chars.
 * Truncates safely at destsize-1 (leaving room for the terminator). */
static inline void lauf_json_escape(const char* src, char* dest, size_t destsize)
{
    size_t j = 0;
    for (size_t i = 0; src[i] != '\0' && j + 6 < destsize; ++i)
    {
        unsigned char c = (unsigned char)src[i];
        if (c == '"' || c == '\\')
        {
            dest[j++] = '\\';
            dest[j++] = (char)c;
        }
        else if (c == '\n')
        {
            dest[j++] = '\\';
            dest[j++] = 'n';
        }
        else if (c == '\r')
        {
            dest[j++] = '\\';
            dest[j++] = 'r';
        }
        else if (c == '\t')
        {
            dest[j++] = '\\';
            dest[j++] = 't';
        }
        else if (c < 0x20)
        {
            int written = snprintf(dest + j, destsize - j, "\\u%04x", c);
            if (written > 0)
                j += (size_t)written;
        }
        else
        {
            dest[j++] = (char)c;
        }
    }
    dest[j] = '\0';
}

/* Per-test wall-clock timeout in seconds. If a forked child hangs (e.g. a
 * fiber scheduler deadlock, a busy loop), the parent SIGKILLs it after this
 * many seconds and records the test as failed rather than blocking the whole
 * group binary. 30s is generously above the expected worst-case for any
 * single well-formed test in the suite. */
#ifndef LAUF_TEST_PER_TEST_TIMEOUT_SEC
#    define LAUF_TEST_PER_TEST_TIMEOUT_SEC 30
#endif

/* Runs every entry in `T` under fork+wait for crash isolation. Writes a JSON
 * array of per-test results to `outpath`. Returns the count of passed tests
 * (which the caller ignores — the exit code is not what determines reward;
 * the CTRF is).
 *
 * Each forked child is bounded by LAUF_TEST_PER_TEST_TIMEOUT_SEC; if the
 * child does not exit within that window the parent SIGKILLs it and records
 * a "timeout" failure. This isolates hangs to a single test rather than
 * letting one bad test consume the entire test.sh budget. */
static inline int lauf_run_group(const TestEntry* T, int n, const char* outpath)
{
    FILE* fp = fopen(outpath, "w");
    if (fp == NULL)
    {
        fprintf(stderr, "harness: cannot open %s: %s\n", outpath, strerror(errno));
        return -1;
    }
    fprintf(fp, "[");
    int passed = 0;
    for (int i = 0; i < n; ++i)
    {
        Result* sh = (Result*)mmap(NULL, sizeof(Result), PROT_READ | PROT_WRITE,
                                   MAP_SHARED | MAP_ANONYMOUS, -1, 0);
        if (sh == MAP_FAILED)
        {
            fprintf(stderr, "harness: mmap failed for test %s: %s\n", T[i].name, strerror(errno));
            fprintf(fp,
                    "%s{\"name\":\"%s\",\"status\":\"failed\",\"duration\":0,"
                    "\"message\":\"harness mmap failed\"}",
                    i ? "," : "", T[i].name);
            continue;
        }
        sh->name   = T[i].name;
        sh->passed = 1;
        sh->msg[0] = '\0';
        cur        = sh;
        pid_t pid  = fork();
        if (pid == 0)
        {
            T[i].fn();
            _exit(cur->passed ? 0 : 1);
        }

        /* Poll for child exit with a wall-clock timeout. We use a busy-wait
         * on waitpid(WNOHANG) with 50ms sleeps because signal-based alarms
         * would fight with lauf's own signal handling in the child. */
        int  st        = 0;
        int  timed_out = 0;
        long slept_ms  = 0;
        const long timeout_ms = (long)LAUF_TEST_PER_TEST_TIMEOUT_SEC * 1000;
        for (;;)
        {
            pid_t r = waitpid(pid, &st, WNOHANG);
            if (r == pid)
                break;
            if (r < 0)
            {
                if (errno == EINTR)
                    continue;
                break;
            }
            if (slept_ms >= timeout_ms)
            {
                timed_out = 1;
                kill(pid, SIGKILL);
                /* Reap the killed child so it doesn't become a zombie. */
                waitpid(pid, &st, 0);
                break;
            }
            /* Sleep 50ms then re-check. */
            struct timespec ts = {0, 50 * 1000 * 1000};
            nanosleep(&ts, NULL);
            slept_ms += 50;
        }

        int  ok = 0;
        char msg[512];
        msg[0] = '\0';
        if (timed_out)
        {
            snprintf(msg, sizeof msg, "test timed out after %d seconds",
                     LAUF_TEST_PER_TEST_TIMEOUT_SEC);
        }
        else if (WIFEXITED(st))
        {
            ok = sh->passed;
            memcpy(msg, sh->msg, sizeof msg);
        }
        else if (WIFSIGNALED(st))
        {
            snprintf(msg, sizeof msg, "test crashed (signal %d)", WTERMSIG(st));
        }
        else
        {
            snprintf(msg, sizeof msg, "test terminated abnormally");
        }
        if (ok)
            ++passed;
        char emsg[1024];
        lauf_json_escape(msg, emsg, sizeof emsg);
        fprintf(fp, "%s{\"name\":\"%s\",\"status\":\"%s\",\"duration\":0,\"message\":\"%s\"}",
                i ? "," : "", T[i].name, ok ? "passed" : "failed", emsg);
        munmap(sh, sizeof(Result));
    }
    fprintf(fp, "]");
    fclose(fp);
    fprintf(stderr, "group passed %d/%d\n", passed, n);
    return passed;
}

/* Silence "unused function" warnings if a group doesn't use every helper. */
static inline void lauf_harness_touch(void)
{
    (void)lauf_json_escape;
    (void)lauf_run_group;
}

#endif /* LAUF_TEST_HARNESS_H */
