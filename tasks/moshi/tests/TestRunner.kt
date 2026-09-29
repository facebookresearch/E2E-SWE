package wrg.hidden

import java.io.File
import org.junit.platform.engine.TestExecutionResult
import org.junit.platform.engine.discovery.DiscoverySelectors.selectClass
import org.junit.platform.launcher.TestIdentifier
import org.junit.platform.launcher.TestExecutionListener
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder.request
import org.junit.platform.launcher.core.LauncherFactory

/**
 * Standalone JUnit 5 runner for the hidden suite — no Gradle, no console launcher, no Python.
 * Discovers and executes `wrg.hidden.MoshiTest`, collects per-test results, and writes a
 * CTRF-format JSON report to the path in args[0]. Exits non-zero if any test failed or if zero
 * tests ran, so test.sh can derive the reward from the exit code without parsing JSON.
 *
 * CTRF schema (the WRG grader reads results.summary.{tests,passed,failed} and results.tests[]):
 *   {"results": {"tool": {"name": "junit5"},
 *                "summary": {"tests": N, "passed": P, "failed": F, "skipped": S,
 *                            "pending": 0, "other": 0, "start": 0, "stop": 0},
 *                "tests": [{"name": "...", "status": "passed|failed|skipped", "duration": 0,
 *                           "message": "..."}]}}
 */

private data class Result(val name: String, val status: String, val message: String?)

private fun jsonEscape(s: String): String = buildString {
  for (c in s) when (c) {
    '\\' -> append("\\\\")
    '"' -> append("\\\"")
    '\n' -> append("\\n")
    '\r' -> append("\\r")
    '\t' -> append("\\t")
    else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
  }
}

fun main(args: Array<String>) {
  val outPath = if (args.isNotEmpty()) args[0] else "ctrf.json"
  val testClassNames = listOf("wrg.hidden.MoshiTest")

  val results = mutableListOf<Result>()
  val listener = object : TestExecutionListener {
    override fun executionFinished(id: TestIdentifier, result: TestExecutionResult) {
      if (!id.isTest) return
      val name = id.displayName.removeSuffix("()")
      val status = when (result.status) {
        TestExecutionResult.Status.SUCCESSFUL -> "passed"
        TestExecutionResult.Status.ABORTED -> "skipped"
        else -> "failed"
      }
      val msg = result.throwable.orElse(null)?.let {
        (it::class.qualifiedName ?: "Throwable") + ": " + (it.message ?: "")
      }
      results += Result(name, status, msg)
    }

    override fun executionSkipped(id: TestIdentifier, reason: String) {
      if (!id.isTest) return
      results += Result(id.displayName.removeSuffix("()"), "skipped", reason)
    }
  }

  val builder = request()
  testClassNames.forEach { builder.selectors(selectClass(Class.forName(it))) }
  LauncherFactory.create().execute(builder.build(), listener)

  val passed = results.count { it.status == "passed" }
  val failed = results.count { it.status == "failed" }
  val skipped = results.count { it.status == "skipped" }
  val total = results.size

  val sb = StringBuilder()
  sb.append("{\n  \"results\": {\n")
  sb.append("    \"tool\": {\"name\": \"junit5\"},\n")
  sb.append("    \"summary\": {")
  sb.append("\"tests\": $total, \"passed\": $passed, \"failed\": $failed, ")
  sb.append("\"skipped\": $skipped, \"pending\": 0, \"other\": 0, \"start\": 0, \"stop\": 0},\n")
  sb.append("    \"tests\": [\n")
  results.forEachIndexed { i, r ->
    sb.append("      {\"name\": \"${jsonEscape(r.name)}\", \"status\": \"${r.status}\", \"duration\": 0")
    if (r.message != null) sb.append(", \"message\": \"${jsonEscape(r.message)}\"")
    sb.append("}")
    sb.append(if (i != results.lastIndex) ",\n" else "\n")
  }
  sb.append("    ]\n  }\n}\n")

  File(outPath).apply { parentFile?.mkdirs() }.writeText(sb.toString())
  println("CTRF -> $outPath: total=$total passed=$passed failed=$failed skipped=$skipped")

  // Exit non-zero unless every test ran and passed (test.sh maps exit code -> reward.txt).
  if (total == 0 || failed > 0 || skipped > 0 || passed != total) {
    System.exit(1)
  }
}
