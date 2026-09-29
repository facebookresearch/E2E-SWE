import { pubThenSubRaw } from './_cli'

// Default (human-readable) sub output: it reports the topic, the decoded payload, the QoS, and a
// human-formatted byte size for each received message.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: default output mode', () => {
  it('prints the topic and payload for a received message', async () => {
    const topic = T('defout')
    const out = await pubThenSubRaw(topic, ['-m', 'hello'], [], /hello/)
    expect(out).toMatch(/hello/)
    expect(out).toContain(topic)
  })

  it('reports a human-readable payload size (formatBytes)', async () => {
    // a 5-byte payload ("hello") is reported as "5B".
    const out = await pubThenSubRaw(T('defsize'), ['-m', 'hello'], [], /5\s?B/)
    expect(out).toMatch(/5\s?B/)
  })

  it('reports the QoS of a received message', async () => {
    // Published and subscribed at QoS 1, so the reported QoS is 1. The topic deliberately omits the
    // substring "qos" so the assertion keys on the rendered qos field, not the echoed topic line.
    const out = await pubThenSubRaw(T('deflevel'), ['-m', 'q', '-q', '1'], ['-q', '1'], /qos/i)
    const clean = out.replace(/\x1b\[[0-9;]*m/g, '') // strip ANSI color so digits in codes don't interfere
    expect(clean.toLowerCase()).toMatch(/qos[^0-9\n]*1\b/)
  })

  it('prints the full MQTT packet in verbose mode (-v)', async () => {
    const out = await pubThenSubRaw(T('verbose'), ['-m', 'vmsg'], ['-v'], /packet|publish/i)
    expect(out.toLowerCase()).toMatch(/packet|publish/)
    expect(out).toContain('vmsg')
  })
})
