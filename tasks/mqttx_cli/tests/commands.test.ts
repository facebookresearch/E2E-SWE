import { run, HOST, simulateThenSubClean, benchSubReceives } from './_cli'

// Auxiliary commands: `ls` (list scenarios), `simulate` (scenario-driven publishing), and the
// `bench` benchmark subcommands.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: ls / simulate / bench', () => {
  it('ls --scenarios lists the built-in scenarios', () => {
    const r = run(['ls', '--scenarios'])
    expect(r.code).toBe(0)
    // The built-in scenarios shipped with the tool.
    expect(r.out).toMatch(/smart_home/)
    expect(r.out).toMatch(/tesla/)
    expect(r.out).toMatch(/weather/)
  })

  it('simulate requires a scenario (-sc) or file (-f)', () => {
    const r = run(['simulate', ...HOST, '-t', 'x'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/scenario|not specified|required/)
  })

  it('simulate rejects an unknown scenario', () => {
    const r = run(['simulate', ...HOST, '-sc', 'does_not_exist', '-t', 'x'])
    expect(r.code).not.toBe(0)
    expect(r.out.toLowerCase()).toMatch(/not found|scenario/)
  })

  // These assert that each scenario runs end-to-end and publishes its scenario-specific structured
  // JSON to the topic. Field VALUES are randomly generated, so we assert the deterministic top-level
  // KEY structure each scenario emits (its observable data contract), not the values.
  const parseScenario = (payload: string): any => {
    const data = JSON.parse(payload)
    expect(typeof data).toBe('object')
    expect(data).not.toBeNull()
    expect(Array.isArray(data)).toBe(false)
    return data
  }

  it('simulate publishes structured data for the smart_home scenario', async () => {
    const m = await simulateThenSubClean('smart_home', T('sim'))
    expect(m.topic).toContain('sim')
    const data = parseScenario(m.payload)
    expect(data).toHaveProperty('home_id')
    expect(Array.isArray(data.rooms)).toBe(true)
    expect(data.rooms.length).toBeGreaterThan(0)
    expect(data.rooms[0]).toHaveProperty('room_type')
    expect(data.rooms[0]).toHaveProperty('temperature')
    expect(data.rooms[0]).toHaveProperty('humidity')
  })

  it('simulate publishes structured data for the tesla scenario', async () => {
    const m = await simulateThenSubClean('tesla', T('tesla'))
    const data = parseScenario(m.payload)
    expect(data).toHaveProperty('model')
    expect(data).toHaveProperty('state')
    expect(data).toHaveProperty('battery_level')
  })

  it('simulate publishes structured data for the weather scenario', async () => {
    const m = await simulateThenSubClean('weather', T('weather'))
    const data = parseScenario(m.payload)
    expect(data).toHaveProperty('station_id')
    expect(typeof data.current).toBe('object')
    expect(data.current).not.toBeNull()
    expect(data.current).toHaveProperty('temp_c')
    expect(data.current).toHaveProperty('humidity')
  })

  it('simulate publishes structured data for the IEM scenario', async () => {
    const m = await simulateThenSubClean('IEM', T('iem'))
    const data = parseScenario(m.payload)
    expect(data).toHaveProperty('factory_id')
    expect(data).toHaveProperty('factory')
    expect(typeof data.values).toBe('object')
    expect(data.values).not.toBeNull()
  })

  it('bench conn creates the requested number of connections', () => {
    const r = run(['bench', 'conn', ...HOST, '-c', '2', '-i', '20'])
    expect(r.out).toMatch(/Created 2 connections/)
  })

  it('bench pub publishes the requested number of messages', () => {
    const r = run(['bench', 'pub', ...HOST, '-c', '1', '-L', '2', '-im', '200', '-t', T('bench'), '-m', 'benchmsg'])
    expect(r.out).toMatch(/Published total: 2/)
  })

  it('bench sub reports received messages', async () => {
    const out = await benchSubReceives(T('bsub'), 2)
    expect(out).toMatch(/Received total: [1-9]/)
  })
})
