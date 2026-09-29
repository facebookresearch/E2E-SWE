import { pubThenSubClean, captureUntil, HOST } from './_cli'

// Core pub/sub behavior: round-trip, retain, QoS levels, protocol versions, random payload sizing,
// connection.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: core pub/sub', () => {
  it('publishes and subscribes a message (round-trip)', async () => {
    const m = await pubThenSubClean(T('basic'), ['-m', 'hello world'])
    expect(m.payload).toBe('hello world')
  })

  it('marks a retained message as retained in the packet', async () => {
    const m = await pubThenSubClean(T('retain'), ['-m', 'keep'])
    expect(m.packet.retain).toBe(true)
  })

  it('round-trips a nonzero-QoS message (QoS 2)', async () => {
    const m = await pubThenSubClean(T('q2'), ['-m', 'q2msg', '-q', '2'], ['-q', '2'])
    expect(m.payload).toBe('q2msg')
    expect(m.packet.qos).toBe(2)
  })

  it('downgrades delivered QoS to the subscription maximum', async () => {
    // published at QoS 2 but subscribed at QoS 0 → delivered at QoS 0.
    const m = await pubThenSubClean(T('qdg'), ['-m', 'dgrade', '-q', '2'], ['-q', '0'])
    expect(m.packet.qos).toBe(0)
  })

  it('connects and publishes with MQTT 3.1.1', async () => {
    const m = await pubThenSubClean(T('v311'), ['-m', 'legacy', '-V', '3.1.1'], ['-V', '3.1.1'])
    expect(m.payload).toBe('legacy')
  })

  it('generates a random payload of the requested size (--payload-size 1KB)', async () => {
    // Measure the delivered payload's byte size through the spec-guaranteed `sub -f base64`
    // rendering (payload's bytes rendered as base64), not the unspecified MQTT-internal packet.length.
    const m = await pubThenSubClean(T('size'), ['-S', '1KB'], ['-f', 'base64'])
    expect(Buffer.from(m.payload, 'base64').length).toBe(1024)
  })

  it('honors a byte-unit payload size (--payload-size 512B)', async () => {
    const m = await pubThenSubClean(T('size512'), ['-S', '512B'], ['-f', 'base64'])
    expect(Buffer.from(m.payload, 'base64').length).toBe(512)
  })

  it('an explicit --message overrides --payload-size', async () => {
    const m = await pubThenSubClean(T('sizeguard'), ['-S', '1KB', '-m', 'literal'])
    expect(m.payload).toBe('literal')
  })

  it('conn connects to the broker successfully', async () => {
    const out = await captureUntil(['conn', ...HOST], /connected/i)
    expect(out.toLowerCase()).toMatch(/connected/)
  })
})
