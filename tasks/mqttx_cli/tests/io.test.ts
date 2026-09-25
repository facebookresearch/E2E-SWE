import { pubThenSubClean, stdinPubThenSubClean, subToFile, subFileSaveCount, subFileWriteDelimited, MSGFILE } from './_cli'

// Message I/O: reading the publish payload from a file (--file-read) or stdin (-s), and writing
// received messages to a file (--file-write).
const T = (n: string) => `wrg/${n}/${Date.now()}`

describe('mqttx cli: file & stdin I/O', () => {
  it('publishes a payload read from a file (--file-read)', async () => {
    const m = await pubThenSubClean(T('fread'), ['--file-read', MSGFILE])
    expect(m.payload).toContain('fromfile-content')
  })

  it('publishes a payload read from stdin (-s)', async () => {
    const m = await stdinPubThenSubClean(T('stdin'), 'stdinmsg\n')
    expect(m.payload).toContain('stdinmsg')
  })

  it('writes a received message to a file (--file-write)', async () => {
    const contents = await subToFile(T('fwrite'), ['-m', 'writtenmsg'])
    expect(contents).toContain('writtenmsg')
  })

  it('writes each received message to a new file (--file-save)', async () => {
    const count = await subFileSaveCount(T('fsave'), 2)
    expect(count).toBeGreaterThanOrEqual(2)
  })

  it('separates file-written messages with --delimiter', async () => {
    const contents = await subFileWriteDelimited(T('delim'), '|')
    expect(contents).toContain('aa|')
    expect(contents).toContain('bb|')
  })
})
