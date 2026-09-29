// Custom doctest reporter that emits a CTRF (Common Test Report Format) JSON file
// directly from C++ — no pytest wrapper. Each doctest TEST_CASE becomes one CTRF
// `results.tests[]` entry; `results.summary` carries the passed/failed/other counts.
//
// The WRG grader (wrg_grader.py::_parse_and_score) reads exactly:
//   results.summary.passed   (numerator of the pass %),
//   results.summary.failed, results.summary.other  (must both be 0 for reward==1),
//   results.tests[]          (list must exist; name/status/message read in verbose mode).
// The denominator is task.toml [verifier] test_case_count (NOT derived from this file),
// so a component whose binary fails to compile is simply ABSENT here and its cases do
// not count as passed — the pass % drops correctly with no synthesized entries needed.
//
// Output path: env var YAFF_CTRF_OUT (each per-component binary writes its own partial
// JSON; test.sh merges the partials into /logs/verifier/ctrf.json). Falls back to
// doctest's --out / stdout only if the env var is unset.
#include "doctest.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <ostream>
#include <string>
#include <vector>

namespace yaffctrf {

// Minimal JSON string escaper (control chars, quotes, backslashes).
inline std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 16);
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c & 0xff);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

struct CtrfEntry {
    std::string name;
    std::string status;   // "passed" | "failed"
    std::string message;  // failure/exception detail (empty on pass)
    double duration_ms = 0.0;
};

struct CtrfReporter : public doctest::IReporter {
    const doctest::ContextOptions& opt;
    const doctest::TestCaseData* tc = nullptr;
    std::vector<CtrfEntry> entries;
    std::string current_exception;  // accumulated for the in-flight case
    std::mutex mutex;

    explicit CtrfReporter(const doctest::ContextOptions& co) : opt(co) {}

    // ---- run lifecycle ----
    void report_query(const doctest::QueryData&) override {}
    void test_run_start() override {}

    void test_run_end(const doctest::TestRunStats&) override {
        std::lock_guard<std::mutex> lock(mutex);
        int passed = 0, failed = 0;
        for (const auto& e : entries) {
            if (e.status == "passed") {
                ++passed;
            } else {
                ++failed;
            }
        }
        const int total = static_cast<int>(entries.size());

        std::string json;
        json += "{\n  \"results\": {\n";
        json += "    \"summary\": {";
        json += "\"tests\": " + std::to_string(total);
        json += ", \"passed\": " + std::to_string(passed);
        json += ", \"failed\": " + std::to_string(failed);
        json += ", \"skipped\": 0";
        json += ", \"pending\": 0";
        json += ", \"other\": 0";
        json += "},\n";
        json += "    \"tests\": [\n";
        for (size_t i = 0; i < entries.size(); ++i) {
            const auto& e = entries[i];
            json += "      {\"name\": \"" + json_escape(e.name) + "\"";
            json += ", \"status\": \"" + e.status + "\"";
            json += ", \"duration\": " + std::to_string(e.duration_ms);
            if (!e.message.empty()) {
                json += ", \"message\": \"" + json_escape(e.message) + "\"";
            }
            json += "}";
            if (i + 1 < entries.size()) {
                json += ",";
            }
            json += "\n";
        }
        json += "    ]\n  }\n}\n";

        const char* out_path = std::getenv("YAFF_CTRF_OUT");
        if (out_path != nullptr && out_path[0] != '\0') {
            std::ofstream ofs(out_path, std::ios::out | std::ios::trunc);
            ofs << json;
            ofs.flush();
        } else {
            // Fallback: write to doctest's configured output stream (stdout by default).
            if (opt.cout != nullptr) {
                *opt.cout << json;
            } else {
                std::fputs(json.c_str(), stdout);
            }
        }
    }

    // ---- per-case lifecycle ----
    void test_case_start(const doctest::TestCaseData& in) override {
        tc = &in;
        current_exception.clear();
    }

    void test_case_reenter(const doctest::TestCaseData&) override {}

    void test_case_end(const doctest::CurrentTestCaseStats& st) override {
        std::lock_guard<std::mutex> lock(mutex);
        CtrfEntry e;
        e.name = (tc != nullptr && tc->m_name != nullptr) ? tc->m_name : "<unknown>";
        e.duration_ms = st.seconds * 1000.0;
        if (st.testCaseSuccess) {
            e.status = "passed";
        } else {
            e.status = "failed";
            if (!current_exception.empty()) {
                e.message = current_exception;
            } else {
                e.message = "assertion(s) failed (" +
                            std::to_string(st.numAssertsFailedCurrentTest) + "/" +
                            std::to_string(st.numAssertsCurrentTest) + " asserts)";
            }
        }
        entries.push_back(std::move(e));
    }

    void test_case_exception(const doctest::TestCaseException& e) override {
        current_exception = std::string("exception: ") +
                            e.error_string.c_str() + (e.is_crash ? " (crash)" : "");
    }

    // ---- unused hooks ----
    void subcase_start(const doctest::SubcaseSignature&) override {}
    void subcase_end() override {}
    void log_assert(const doctest::AssertData&) override {}
    void log_message(const doctest::MessageData&) override {}

    void test_case_skipped(const doctest::TestCaseData&) override {}
};

}  // namespace yaffctrf

// priority 1 so it is not treated as the "default" reporter; activate with --reporters=ctrf.
DOCTEST_REGISTER_REPORTER("ctrf", 1, yaffctrf::CtrfReporter);
