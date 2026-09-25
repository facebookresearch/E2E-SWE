import { pubThenSubClean } from './_cli'

// MQTT 5.0 message properties carried on publish and surfaced in the received packet.
// All are documented publish options; each round-trips through the broker to a subscriber.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: MQTT 5.0 publish properties', () => {
  it('carries multiple user properties (repeated -up)', async () => {
    const m = await pubThenSubClean(T('mup'), ['-m', 'hi', '-up', 'a: 1', '-up', 'b: 2'])
    const up = (m.packet.properties || {}).userProperties || {}
    expect(up.a).toBe('1')
    expect(up.b).toBe('2')
  })

  it('carries the message-expiry-interval', async () => {
    const m = await pubThenSubClean(T('mei'), ['-m', 'hi', '-e', '120'])
    const mei = (m.packet.properties || {}).messageExpiryInterval
    // The broker forwards a (possibly slightly decremented) expiry interval.
    expect(typeof mei).toBe('number')
    expect(mei).toBeGreaterThan(100)
    expect(mei).toBeLessThanOrEqual(120)
  })

  it('carries the response-topic', async () => {
    const m = await pubThenSubClean(T('rt'), ['-m', 'hi', '-rt', 'reply/here'])
    expect((m.packet.properties || {}).responseTopic).toBe('reply/here')
  })

  it('carries correlation-data', async () => {
    const m = await pubThenSubClean(T('cd'), ['-m', 'hi', '-cd', 'abc123'])
    const cd = (m.packet.properties || {}).correlationData
    // Serialized as a Buffer ({ type: 'Buffer', data: [...] }); its bytes must be the input string.
    const bytes = cd && (cd.data || cd)
    expect(Buffer.from(bytes).toString()).toBe('abc123')
  })

  it('carries the payload-format-indicator (-pf)', async () => {
    const m = await pubThenSubClean(T('pf'), ['-m', 'hi', '-pf'])
    expect((m.packet.properties || {}).payloadFormatIndicator).toBe(true)
  })

  it('carries several properties together on one publish', async () => {
    const m = await pubThenSubClean(T('combo'), ['-m', 'hi', '-up', 'k: v', '-ct', 'text/plain', '-rt', 'r/t'])
    const p = m.packet.properties || {}
    expect((p.userProperties || {}).k).toBe('v')
    expect(p.contentType).toBe('text/plain')
    expect(p.responseTopic).toBe('r/t')
  })
})
