import { run, HOST, subCleanOnce } from './_cli'
import * as os from 'os'
import * as path from 'path'

// Saving command options to a config file (-so) and loading them back (-lo). Loaded options are
// merged with (and overridden by) any options given explicitly on the command line.
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: save/load options', () => {
  it('saves options to a config file and reloads them (-so / -lo)', async () => {
    const topic = T('cfg')
    const cfg = path.join(os.tmpdir(), `mqttx-cfg-${process.pid}-${Date.now()}.json`)

    // Save the pub options (topic + retain) to the config file. (-so also publishes.)
    const save = run(['pub', ...HOST, '-t', topic, '-m', 'cfgmsg', '-r', '-so', cfg])
    expect(save.code).toBe(0)
    expect(save.out.toLowerCase()).toMatch(/saved|config/)

    // Load the config (topic comes from the file, NOT the command line) and override only the message.
    const load = run(['pub', '-lo', cfg, '-m', 'loadedmsg'])
    expect(load.code).toBe(0)

    // The retained message on the config's topic must now be the overridden message — proving the
    // topic was loaded from the file and the CLI value overrode the saved message.
    const m = await subCleanOnce(topic)
    expect(m.payload).toBe('loadedmsg')
  })
})
