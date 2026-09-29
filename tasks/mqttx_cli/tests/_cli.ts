// Helpers for the mqttx CLI hidden tests. Not a *.test.ts file. Drives the built CLI (spawned via
// $MQTTX_CLI) against a local mosquitto broker: TCP on 127.0.0.1:1883, WebSocket on 127.0.0.1:8083.
import { spawnSync, exec, spawn } from 'child_process'
import * as path from 'path'
import * as os from 'os'
import * as fs from 'fs'

export const CLI = process.env.MQTTX_CLI || '/app/bin/index.js'
export const HOST = ['-h', '127.0.0.1', '-p', '1883'] // TCP broker
export const WS = ['-h', '127.0.0.1', '-p', '8083', '-l', 'ws', '--path', '/mqtt'] // WebSocket broker

// Fixtures shipped alongside the tests.
export const PROTO = path.join(__dirname, 'person.proto')
export const AVSC = path.join(__dirname, 'user.avsc')
export const MSGFILE = path.join(__dirname, 'msg.txt')

/** Run a CLI command to completion; return exit code + combined stdout/stderr. */
export function run(args: string[], input?: string): { code: number | null; out: string } {
  const r = spawnSync('node', [CLI, ...args], { encoding: 'utf8', timeout: 25000, input })
  return { code: r.status, out: (r.stdout || '') + (r.stderr || '') }
}

/** Subscribe (clean mode) to one or more topics and resolve the first parsed message object. */
function subCleanFirst(topics: string[], subArgs: string[], conn: string[], timeoutMs: number): Promise<any> {
  const topicFlags = topics.map((t) => `-t ${t}`).join(' ')
  return new Promise((resolve, reject) => {
    const child = exec(`node ${CLI} sub ${conn.join(' ')} ${topicFlags} ${subArgs.join(' ')} --output-mode clean`)
    let out = ''
    // stderr is kept OUT of `out` (it must not perturb the JSON match) but is reported on timeout so a
    // silent subscriber failure shows its real error instead of a bare `timeout; sub=`.
    let err = ''
    let done = false
    const timer = setTimeout(() => finish(new Error('timeout; sub=' + out + '; err=' + err)), timeoutMs)
    function finish(e?: Error, val?: any) {
      if (done) return
      done = true
      clearTimeout(timer)
      try { child.kill() } catch {}
      if (val !== undefined) resolve(val)
      else reject(e)
    }
    child.stdout?.on('data', (d) => {
      out += d.toString()
      const m = out.match(/\{[\s\S]*\}/)
      if (m) {
        try { finish(undefined, JSON.parse(m[0])) } catch { /* wait for more */ }
      }
    })
    child.stderr?.on('data', (d) => { err += d.toString() })
  })
}

/** Subscribe (clean mode) to a single topic and resolve the first message. Assumes the message is
 *  already retained on the topic (published beforehand). */
export function subCleanOnce(topic: string, subArgs: string[] = [], timeoutMs = 6000): Promise<any> {
  return subCleanFirst([topic], subArgs, HOST, timeoutMs)
}

/** Subscribe with `--file-save <dir>/msg.txt`, publish `n` messages, and return the number of files
 *  created in the dir (the CLI writes each message to a new numbered file). */
export function subFileSaveCount(topic: string, n = 2): Promise<number> {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fs-'))
  const child = exec(`node ${CLI} sub ${HOST.join(' ')} -t ${topic} --file-save ${dir}/msg.txt`)
  return new Promise((resolve) => {
    setTimeout(() => {
      for (let i = 0; i < n; i++) {
        spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, '-m', `m${i}`], { encoding: 'utf8', timeout: 15000 })
      }
      setTimeout(() => {
        try { child.kill() } catch {}
        let c = 0
        try { c = fs.readdirSync(dir).length } catch {}
        resolve(c)
      }, 2000)
    }, 1500)
  })
}

/** Subscribe with `--file-write <file> --delimiter <delim>`, publish two messages, return the file. */
export function subFileWriteDelimited(topic: string, delim = '|'): Promise<string> {
  const out = path.join(os.tmpdir(), `fwd-${process.pid}-${topic.replace(/\W/g, '')}.out`)
  const child = exec(`node ${CLI} sub ${HOST.join(' ')} -t ${topic} --file-write ${out} --delimiter '${delim}'`)
  return new Promise((resolve) => {
    setTimeout(() => {
      spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, '-m', 'aa'], { encoding: 'utf8', timeout: 15000 })
      spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, '-m', 'bb'], { encoding: 'utf8', timeout: 15000 })
      setTimeout(() => {
        try { child.kill() } catch {}
        let c = ''
        try { c = fs.readFileSync(out, 'utf8') } catch {}
        resolve(c)
      }, 1800)
    }, 1500)
  })
}

/** Publish a RETAINED message to a unique topic, then subscribe (clean mode) and resolve the first
 *  parsed message object `{topic, payload, packet}`. Retained delivery makes this deterministic.
 *  `conn` selects the transport (default TCP HOST; pass WS for websocket). */
export function pubThenSubClean(
  topic: string,
  pubArgs: string[],
  subArgs: string[] = [],
  conn: string[] = HOST,
  timeoutMs = 6000,
): Promise<any> {
  spawnSync('node', [CLI, 'pub', ...conn, '-t', topic, ...pubArgs, '-r'], { encoding: 'utf8', timeout: 15000 })
  return subCleanFirst([topic], subArgs, conn, timeoutMs)
}

/** Like pubThenSubClean, but subscribes to MULTIPLE topics at once (repeated -t). */
export function pubThenSubCleanMulti(
  pubTopic: string,
  subTopics: string[],
  pubArgs: string[] = [],
  timeoutMs = 6000,
): Promise<any> {
  spawnSync('node', [CLI, 'pub', ...HOST, '-t', pubTopic, ...pubArgs, '-r'], { encoding: 'utf8', timeout: 15000 })
  return subCleanFirst(subTopics, [], HOST, timeoutMs)
}

/** Publish via STDIN (`-s`), then clean-sub and resolve the first message. */
export function stdinPubThenSubClean(topic: string, input: string, timeoutMs = 6000): Promise<any> {
  spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, '-s', '-r'], { encoding: 'utf8', timeout: 15000, input })
  return subCleanFirst([topic], [], HOST, timeoutMs)
}

/** Publish a RETAINED message then subscribe in DEFAULT output mode, resolving raw stdout as soon as
 *  `matcher` appears (or after maxMs). Needed for schema (protobuf/avro) decode and the human-readable
 *  default-mode output, which the CLI produces only in default mode. */
export function pubThenSubRaw(
  topic: string,
  pubArgs: string[],
  subArgs: string[] = [],
  matcher?: RegExp,
  maxMs = 9000,
): Promise<string> {
  spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, ...pubArgs, '-r'], { encoding: 'utf8', timeout: 15000 })
  return new Promise((resolve) => {
    const child = exec(`node ${CLI} sub ${HOST.join(' ')} -t ${topic} ${subArgs.join(' ')}`)
    let out = ''
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(timer); try { child.kill() } catch {} ; resolve(out) }
    const timer = setTimeout(finish, maxMs)
    const onData = (d: Buffer) => { out += d.toString(); if (matcher && matcher.test(out)) finish() }
    child.stdout?.on('data', onData)
    child.stderr?.on('data', onData)
  })
}

/** Run a (possibly long-running) command and resolve combined output once `matcher` appears (or after
 *  maxMs), then kill it. Used for `conn` (stays connected) and similar. */
export function captureUntil(args: string[], matcher: RegExp, maxMs = 8000): Promise<string> {
  return new Promise((resolve) => {
    const child = spawn('node', [CLI, ...args])
    let out = ''
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(timer); try { child.kill('SIGKILL') } catch {} ; resolve(out) }
    const timer = setTimeout(finish, maxMs)
    const onData = (d: Buffer) => { out += d.toString(); if (matcher.test(out)) finish() }
    child.stdout?.on('data', onData)
    child.stderr?.on('data', onData)
  })
}

/** Start a `sub --file-write <file>`, publish once, then return the file's contents. */
export function subToFile(topic: string, pubArgs: string[] = ['-m', 'writtenmsg']): Promise<string> {
  const outFile = path.join(os.tmpdir(), `fw-${process.pid}-${topic.replace(/\W/g, '')}.out`)
  return new Promise((resolve) => {
    const child = exec(`node ${CLI} sub ${HOST.join(' ')} -t ${topic} --file-write ${outFile}`)
    setTimeout(() => {
      spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, ...pubArgs], { encoding: 'utf8', timeout: 15000 })
      setTimeout(() => {
        try { child.kill() } catch {}
        let c = ''
        try { c = fs.readFileSync(outFile, 'utf8') } catch {}
        resolve(c)
      }, 1800)
    }, 1500)
  })
}

/** Run `bench sub`, publish a few messages, and resolve its output once it reports a received total. */
export function benchSubReceives(topic: string, n = 2, timeoutMs = 14000): Promise<string> {
  return new Promise((resolve) => {
    const child = exec(`node ${CLI} bench sub ${HOST.join(' ')} -c 1 -t ${topic}`)
    let out = ''
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(timer); try { child.kill() } catch {} ; resolve(out) }
    const timer = setTimeout(finish, timeoutMs)
    const onData = (d: Buffer) => { out += d.toString(); if (/Received total: [1-9]/.test(out)) finish() }
    child.stdout?.on('data', onData)
    child.stderr?.on('data', onData)
    setTimeout(() => {
      for (let i = 0; i < n; i++) {
        spawnSync('node', [CLI, 'pub', ...HOST, '-t', topic, '-m', 'x'], { encoding: 'utf8', timeout: 15000 })
      }
    }, 2500)
  })
}

/** Start a clean-mode subscriber, then run `simulate` (live, non-retained), resolving the first
 *  received message object. The publisher runs ASYNC (exec, not spawnSync) so the subscriber's output
 *  is processed live while simulate runs; the subscriber gets a generous lead time and simulate emits
 *  several messages to avoid a delivery race. */
export function simulateThenSubClean(scenario: string, topic: string, timeoutMs = 15000): Promise<any> {
  const sub = exec(`node ${CLI} sub ${HOST.join(' ')} -t ${topic} --output-mode clean`)
  let pub: ReturnType<typeof exec> | null = null
  return new Promise((resolve, reject) => {
    let out = ''
    let done = false
    const timer = setTimeout(() => finish(new Error('timeout; sub=' + out)), timeoutMs)
    function finish(err?: Error, val?: any) {
      if (done) return
      done = true
      clearTimeout(timer)
      try { sub.kill() } catch {}
      try { pub && pub.kill() } catch {}
      if (val !== undefined) resolve(val)
      else reject(err)
    }
    sub.stdout?.on('data', (d) => {
      out += d.toString()
      const m = out.match(/\{[\s\S]*\}/)
      if (m) {
        try { finish(undefined, JSON.parse(m[0])) } catch { /* wait */ }
      }
    })
    // Once the subscriber is up, publish several simulated messages asynchronously.
    setTimeout(() => {
      pub = exec(`node ${CLI} simulate ${HOST.join(' ')} -sc ${scenario} -c 1 -L 3 -im 300 -t ${topic}`)
    }, 2500)
  })
}

/** Verify a will message. Registers a will-bearing client with a RETAINED will, waits until it is
 *  actually connected (reads its output), then kills it UNGRACEFULLY (SIGKILL). Because the will is
 *  retained, a subscriber connecting AFTER the kill still receives it — making this deterministic.
 *  `extraWillArgs` can add will properties (e.g. -Wct). Resolves the received message object. */
export function willOnUngracefulDisconnect(
  willTopic: string,
  willMsg: string,
  extraWillArgs: string[] = [],
  timeoutMs = 16000,
): Promise<any> {
  const keepalive = `keepalive/${process.pid}/${willTopic.replace(/\W/g, '')}`
  return new Promise((resolve, reject) => {
    const willClient = spawn('node', [
      CLI, 'sub', ...HOST, '-t', keepalive, '-Wt', willTopic, '-Wm', willMsg, '-Wq', '1', '-Wr', ...extraWillArgs,
    ])
    let ready = false
    let killed = false
    const readyDeadline = Date.now() + 7000
    const onReady = (d: Buffer) => {
      if (/connect|subscrib/i.test(d.toString())) ready = true
    }
    willClient.stdout?.on('data', onReady)
    willClient.stderr?.on('data', onReady)
    // Poll for readiness (or a hard cap), then kill ungracefully and read the retained will.
    const poll = setInterval(() => {
      if (killed) return
      if (ready || Date.now() > readyDeadline) {
        killed = true
        clearInterval(poll)
        setTimeout(() => {
          try { willClient.kill('SIGKILL') } catch {}
          // Give the broker a moment to publish the retained will, then subscribe and read it.
          setTimeout(() => {
            subCleanFirst([willTopic], [], HOST, timeoutMs - 6000).then(resolve).catch(reject)
          }, 1200)
        }, 500)
      }
    }, 150)
  })
}
