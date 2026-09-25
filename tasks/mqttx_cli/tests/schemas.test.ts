import { pubThenSubClean, pubThenSubRaw, PROTO, AVSC } from './_cli'

// Schema-based payload encoding (protobuf / avro), configured via -Pp/-Pmn and -Ap (not -f).
// Encode happens on publish; decode (schema) happens only in the DEFAULT output mode, so round-trip
// decode is asserted via raw default output.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: schema encoding (protobuf/avro)', () => {
  it('protobuf round-trips a JSON message (encode on pub, decode on sub)', async () => {
    const topic = T('pb')
    const out = await pubThenSubRaw(
      topic,
      ['-Pp', PROTO, '-Pmn', 'Person', '-m', '{"name":"alice","id":7}'],
      ['-Pp', PROTO, '-Pmn', 'Person'],
      /"name":"alice"/,
    )
    expect(out).toMatch(/"name":"alice"/)
    expect(out).toMatch(/"id":7/)
  })

  it('protobuf encodes the message to the correct wire bytes', async () => {
    // proto3 encoding of Person{name:"alice", id:7} is deterministic: 0a 05 "alice" 10 07.
    const m = await pubThenSubClean(T('pbhex'), ['-Pp', PROTO, '-Pmn', 'Person', '-m', '{"name":"alice","id":7}'], ['-f', 'hex'])
    expect(m.payload.replace(/\s+/g, '')).toBe('0a05616c6963651007')
  })

  it('avro round-trips a JSON message (encode on pub, decode on sub)', async () => {
    const topic = T('av')
    const out = await pubThenSubRaw(
      topic,
      ['-Ap', AVSC, '-m', '{"name":"bob","age":30}'],
      ['-Ap', AVSC],
      /"name":"bob"/,
    )
    expect(out).toMatch(/"name":"bob"/)
    expect(out).toMatch(/"age":30/)
  })
})
