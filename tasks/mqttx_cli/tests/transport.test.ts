import { pubThenSubClean, pubThenSubCleanMulti, willOnUngracefulDisconnect, WS } from './_cli'

const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: transport, will, multi-topic', () => {
  it('publishes and subscribes over websocket transport', async () => {
    const m = await pubThenSubClean(T('ws'), ['-m', 'wshello'], [], WS)
    expect(m.payload).toBe('wshello')
  })

  it('delivers a will message on ungraceful disconnect', async () => {
    const m = await willOnUngracefulDisconnect(T('will'), 'willbye')
    expect(m.payload).toBe('willbye')
  })

  it('carries a will content-type property (MQTT 5.0)', async () => {
    const m = await willOnUngracefulDisconnect(T('willct'), 'wct', ['-Wct', 'application/json'])
    expect(JSON.stringify(m.packet.properties || {})).toContain('application/json')
  })

  it('subscribing to multiple topics receives a message on any of them', async () => {
    const base = Date.now()
    const first = `mt/first/${base}`
    const second = `mt/second/${base}`
    const m = await pubThenSubCleanMulti(second, [first, second], ['-m', 'onsecond'])
    expect(m.payload).toBe('onsecond')
    expect(m.topic).toBe(second)
  })
})
