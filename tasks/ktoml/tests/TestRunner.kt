package com.akuleshov7.ktoml.hidden

import org.junit.platform.engine.discovery.DiscoverySelectors.selectClass
import org.junit.platform.launcher.TestIdentifier
import org.junit.platform.launcher.TestExecutionListener
import org.junit.platform.launcher.TestPlan
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder.request
import org.junit.platform.launcher.core.LauncherFactory
import org.junit.platform.engine.TestExecutionResult
import java.io.File

/**
 * Standalone JUnit 5 runner that discovers and executes the hidden test class(es),
 * collects per-test results, and writes a CTRF-format JSON report to the path given
 * as the first CLI argument. No network, no Gradle, no JUnit console launcher needed.
 *
 * CTRF schema produced (the WRG grader reads results.summary.{passed,failed} and
 * results.tests[].{name,status}):
 *   {
 *     "results": {
 *       "tool": {"name": "junit5"},
 *       "summary": {"tests": N, "passed": P, "failed": F, "skipped": S, "other": 0,
 *                   "start": 0, "stop": 0},
 *       "tests": [ {"name": "...", "status": "passed|failed|skipped", "duration": 0,
 *                   "message": "..."} ]
 *     }
 *   }
 */

private data class Result(val name: String, val status: String, val message: String?)

private fun jsonEscape(s: String): String {
    val sb = StringBuilder()
    for (c in s) {
        when (c) {
            '\\' -> sb.append("\\\\")
            '"' -> sb.append("\\\"")
            '\n' -> sb.append("\\n")
            '\r' -> sb.append("\\r")
            '\t' -> sb.append("\\t")
            '\b' -> sb.append("\\b")
            '\u000C' -> sb.append("\\f")
            else -> if (c < ' ') sb.append("\\u%04x".format(c.code)) else sb.append(c)
        }
    }
    return sb.toString()
}

fun main(args: Array<String>) {
    val outPath = if (args.isNotEmpty()) args[0] else "ctrf.json"
    val testClassNames = listOf("com.akuleshov7.ktoml.hidden.KtomlTest")

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
                (it::class.qualifiedName ?: it::class.simpleName ?: "Throwable") +
                    ": " + (it.message ?: "")
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
    val launcher = LauncherFactory.create()
    launcher.execute(builder.build(), listener)

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
        if (i != results.lastIndex) sb.append(",")
        sb.append("\n")
    }
    sb.append("    ]\n  }\n}\n")

    val outFile = File(outPath)
    outFile.parentFile?.mkdirs()
    outFile.writeText(sb.toString())

    println("CTRF written to $outPath: total=$total passed=$passed failed=$failed skipped=$skipped")
}
