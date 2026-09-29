/*
 * Shared CTRF test harness. Each test group is its own translation unit / binary so a
 * compile error in one API area (e.g. events) fails only that group, while the others
 * still compile, run, and score (partial credit). Each group binary writes a JSON
 * array of its per-test results to argv[1]; test.sh merges the groups into one CTRF.
 * Every test runs in a forked process so a runtime crash fails only that test.
 */
#ifndef UREACT_TEST_HARNESS_H
#define UREACT_TEST_HARNESS_H

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

typedef struct { const char *name; int passed; char msg[400]; } Result;
static Result *cur;
#define FAIL(...) do { snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__); cur->passed = 0; return; } while (0)
#define CHECK(c, ...) do { if (!(c)) FAIL(__VA_ARGS__); } while (0)

struct TestEntry { const char *name; void (*fn)(void); };

static inline int run_group(const TestEntry *T, int n, const char *outpath) {
    FILE *fp = fopen(outpath, "w");
    if (fp) fprintf(fp, "[");
    int passed = 0;
    for (int i = 0; i < n; i++) {
        Result *sh = (Result *)mmap(NULL, sizeof(Result), PROT_READ | PROT_WRITE,
                                    MAP_SHARED | MAP_ANONYMOUS, -1, 0);
        sh->name = T[i].name; sh->passed = 1; sh->msg[0] = '\0';
        cur = sh;
        pid_t pid = fork();
        if (pid == 0) { T[i].fn(); _exit(cur->passed ? 0 : 1); }
        int st = 0; waitpid(pid, &st, 0);
        int ok; char msg[400];
        if (WIFEXITED(st)) { ok = sh->passed; memcpy(msg, sh->msg, sizeof msg); }
        else { ok = 0; snprintf(msg, sizeof msg, "test crashed (signal %d)", WIFSIGNALED(st) ? WTERMSIG(st) : -1); }
        if (ok) passed++;
        if (fp) fprintf(fp, "%s{\"name\":\"%s\",\"status\":\"%s\",\"duration\":0,\"message\":\"%s\"}",
                        i ? "," : "", T[i].name, ok ? "passed" : "failed", msg);
        munmap(sh, sizeof(Result));
    }
    if (fp) { fprintf(fp, "]"); fclose(fp); }
    printf("group passed %d/%d\n", passed, n);
    return passed;
}

#endif
