// Convert vitest's built-in JSON reporter output into the CTRF schema the WRG
// grader reads (.results.summary + .results.tests[]). Usage:
//   node ctrf_from_vitest.js <vitest-json> <ctrf-out>
const fs = require('fs')
const [, , inPath, outPath] = process.argv
const v = JSON.parse(fs.readFileSync(inPath, 'utf8'))

const tests = []
for (const file of v.testResults || []) {
  for (const a of file.assertionResults || []) {
    const status =
      a.status === 'passed'
        ? 'passed'
        : a.status === 'pending' || a.status === 'skipped' || a.status === 'todo'
          ? 'skipped'
          : 'failed'
    tests.push({
      name: a.fullName || a.title,
      status,
      duration: a.duration || 0,
      ...(status === 'failed' && a.failureMessages?.length
        ? { message: a.failureMessages.join('\n').slice(0, 2000) }
        : {})
    })
  }
}
const passed = tests.filter(t => t.status === 'passed').length
const failed = tests.filter(t => t.status === 'failed').length
const skipped = tests.filter(t => t.status === 'skipped').length

const ctrf = {
  results: {
    tool: { name: 'vitest' },
    summary: {
      tests: tests.length,
      passed,
      failed,
      pending: 0,
      skipped,
      other: 0,
      start: 0,
      stop: 0
    },
    tests
  }
}
fs.mkdirSync(require('path').dirname(outPath), { recursive: true })
fs.writeFileSync(outPath, JSON.stringify(ctrf, null, 2))
console.log(`CTRF written -> ${outPath}: tests=${tests.length} passed=${passed} failed=${failed} skipped=${skipped}`)
