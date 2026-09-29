import { pubThenSubClean } from './_cli'

// Payload format conversions (-f): encode on publish, decode on subscribe.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: payload formats (-f)', () => {
  it('hex format decodes the received payload to its hex bytes', async () => {
    const m = await pubThenSubClean(T('hex'), ['-m', 'Hello'], ['-f', 'hex'])
    expect(m.payload.replace(/\s+/g, '')).toBe('48656c6c6f')
  })

  it('base64 format on publish decodes the input to raw bytes', async () => {
    const m = await pubThenSubClean(T('b64'), ['-m', 'SGVsbG8=', '-f', 'base64'])
    expect(m.payload).toBe('Hello')
  })

  it('hex format on publish decodes the input to raw bytes', async () => {
    const m = await pubThenSubClean(T('hexpub'), ['-m', '48656c6c6f', '-f', 'hex'])
    expect(m.payload).toBe('Hello')
  })

  it('json format preserves big integers beyond 2^53', async () => {
    const m = await pubThenSubClean(T('json'), ['-m', '{"n":9007199254740993}', '-f', 'json'], ['-f', 'json'])
    expect(m.payload).toContain('9007199254740993')
  })

  it('cbor format round-trips a JSON object', async () => {
    const m = await pubThenSubClean(T('cbor'), ['-m', '{"a":1,"b":"x"}', '-f', 'cbor'], ['-f', 'cbor'])
    expect(JSON.parse(m.payload)).toEqual({ a: 1, b: 'x' })
  })

  it('msgpack format round-trips a nested/typed object', async () => {
    const m = await pubThenSubClean(
      T('mp'),
      ['-m', '{"n":42,"arr":[1,2,3],"o":{"x":true}}', '-f', 'msgpack'],
      ['-f', 'msgpack'],
    )
    expect(JSON.parse(m.payload)).toEqual({ n: 42, arr: [1, 2, 3], o: { x: true } })
  })

  it('binary format publishes the input bytes unchanged', async () => {
    const m = await pubThenSubClean(T('bin'), ['-m', 'rawbytes', '-f', 'binary'])
    expect(m.payload).toBe('rawbytes')
  })
})
