// Custom Catch2 v3 reporter that writes results in CTRF (Common Test Report
// Format) JSON directly -- the language-agnostic format the WRG grader consumes
// from /logs/verifier/ctrf.json. This keeps grading fully C++-native: the
// held-out Catch2 tests run once and emit the grader's report themselves, with
// no pytest / pytest-json-ctrf wrapper in between.
//
// Contract (see wrg_grader.py::_parse_and_score): the grader reads only
//   .results.summary.passed / .failed / .other   (other optional, default 0)
// and requires .results.tests to exist (array; per-test fields are used only for
// verbose logging, never for scoring). Reward is max iff
//   passed >= [verifier] test_case_count  AND  failed == 0  AND  other == 0.
// One Catch2 TEST_CASE -> one CTRF test entry.
//
// The noisy [!mayfail] ICP cases are intentionally NOT graded; they are excluded
// here via TestCaseInfo::okToFail(), so they never affect the count even if run.
//
// Usage:  ./rko_lio_core_tests --reporter ctrf --out /logs/verifier/ctrf.json

#include <catch2/catch_test_case_info.hpp>
#include <catch2/catch_totals.hpp>
#include <catch2/interfaces/catch_interfaces_reporter.hpp>
#include <catch2/reporters/catch_reporter_registrars.hpp>
#include <catch2/reporters/catch_reporter_streaming_base.hpp>

#include <cstdio>
#include <ostream>
#include <string>
#include <vector>

namespace {

// Minimal JSON string escaping (quote, backslash, control characters).
std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 2);
  for (char c : s) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\b': out += "\\b"; break;
      case '\f': out += "\\f"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (static_cast<unsigned char>(c) < 0x20) {
          char buf[7];
          std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned int>(static_cast<unsigned char>(c)));
          out += buf;
        } else {
          out += c;
        }
    }
  }
  return out;
}

class CtrfReporter : public Catch::StreamingReporterBase {
 public:
  using Catch::StreamingReporterBase::StreamingReporterBase;

  static std::string getDescription() {
    return "Emits test results as CTRF JSON for the WRG grader";
  }

  // Pass/fail is derived from the per-case totals in testCaseEnded, so the
  // assertion hooks are intentional no-ops.
  void assertionStarting(Catch::AssertionInfo const&) override {}
  void assertionEnded(Catch::AssertionStats const&) override {}

  void testCaseEnded(Catch::TestCaseStats const& stats) override {
    // Skip the non-graded [!mayfail]/[!shouldfail] cases entirely.
    if (stats.testInfo->okToFail()) {
      return;
    }
    // Catch2 passes per-case (delta) totals here; allOk() == no real failures.
    const bool passed = stats.totals.assertions.allOk();
    m_tests.push_back({stats.testInfo->name, passed});
    if (passed) {
      ++m_passed;
    } else {
      ++m_failed;
    }
  }

  void testRunEnded(Catch::TestRunStats const&) override {
    const std::size_t total = m_passed + m_failed;
    m_stream << "{\n";
    m_stream << "  \"reportFormat\": \"CTRF\",\n";
    m_stream << "  \"specVersion\": \"0.0.0\",\n";
    m_stream << "  \"results\": {\n";
    m_stream << "    \"tool\": { \"name\": \"Catch2\" },\n";
    m_stream << "    \"summary\": {\n";
    m_stream << "      \"tests\": " << total << ",\n";
    m_stream << "      \"passed\": " << m_passed << ",\n";
    m_stream << "      \"failed\": " << m_failed << ",\n";
    m_stream << "      \"pending\": 0,\n";
    m_stream << "      \"skipped\": 0,\n";
    m_stream << "      \"other\": 0,\n";
    m_stream << "      \"start\": 0,\n";
    m_stream << "      \"stop\": 0\n";
    m_stream << "    },\n";
    m_stream << "    \"tests\": [\n";
    for (std::size_t i = 0; i < m_tests.size(); ++i) {
      m_stream << "      { \"name\": \"" << json_escape(m_tests[i].name)
               << "\", \"status\": \"" << (m_tests[i].passed ? "passed" : "failed")
               << "\", \"duration\": 0 }" << (i + 1 < m_tests.size() ? "," : "")
               << "\n";
    }
    m_stream << "    ]\n";
    m_stream << "  }\n";
    m_stream << "}\n";
    m_stream.flush();
  }

 private:
  struct TestEntry {
    std::string name;
    bool passed;
  };
  std::vector<TestEntry> m_tests;
  std::size_t m_passed = 0;
  std::size_t m_failed = 0;
};

}  // namespace

CATCH_REGISTER_REPORTER("ctrf", CtrfReporter)
