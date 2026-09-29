import { run, HOST } from './_cli'

// Non-happy-path contract: usage/validation errors print a message and exit non-zero. Assertions check
// the observable contract (non-zero exit + a keyword), not exact wording — an alternative implementation
// may phrase errors differently.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: argument validation & errors', () => {
  it('rejects an invalid --format', () => {
    const r = run(['pub', ...HOST, '-t', 'x', '-m', 'y', '-f', 'xml'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/format/)
  })

  it('rejects an invalid subscribe --qos', () => {
    const r = run(['sub', ...HOST, '-t', 'x', '-q', '3'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/qos/)
  })

  it('rejects an invalid --mqtt-version', () => {
    const r = run(['conn', ...HOST, '-V', '4.0'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/version/)
  })

  it('rejects publishing to a topic with wildcards', () => {
    const r = run(['pub', ...HOST, '-t', 'foo/#', '-m', 'y'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/wildcard|topic/)
  })

  it('requires a --topic for publish', () => {
    const r = run(['pub', ...HOST, '-m', 'y'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/topic/)
  })

  it('requires a --topic for subscribe', () => {
    const r = run(['sub', ...HOST])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/topic/)
  })

  it('rejects an unsupported authentication method', () => {
    const r = run(['conn', ...HOST, '-am', 'BOGUS'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/authentication|scram/)
  })

  it('rejects a malformed user-property (not "key: value")', () => {
    const r = run(['pub', ...HOST, '-t', 'x', '-m', 'y', '-up', 'novalue'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/key-value|key: ?value|invalid|malformed|user[- ]?propert/)
  })

  it('rejects websocket headers on a non-websocket connection', () => {
    const r = run(['pub', ...HOST, '-t', 'x', '-m', 'y', '-wh', 'Authorization: Bearer t'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/websocket/)
  })

  it('errors (non-zero exit) publishing invalid JSON with --format json', () => {
    const r = run(['pub', ...HOST, '-t', T('badjson'), '-f', 'json', '-m', '{not valid json}'])
    expect(r.code).not.toBe(0)
  })

  it('prints a version string', () => {
    const r = run(['--version'])
    expect(r.code).toBe(0) // guard against a crashing CLI whose stderr merely contains a version
    expect(r.out).toMatch(/\d+\.\d+\.\d+/)
  })
})
