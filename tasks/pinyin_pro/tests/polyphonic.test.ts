import { polyphonic } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// polyphonic() returns every reading of each character. The per-character multi-reading output and
// its option handling are bespoke.
describe('polyphonic', () => {
  it('default: space-joined readings per character', () => {
    expect(polyphonic('好好学习')).toEqual(['hǎo hào', 'hǎo hào', 'xué', 'xí'])
  })

  it('type: array', () => {
    expect(polyphonic('好好学习', { type: 'array' })).toEqual([['hǎo', 'hào'], ['hǎo', 'hào'], ['xué'], ['xí']])
  })

  it('pattern: num', () => {
    expect(polyphonic('好好学习', { pattern: 'num' })).toEqual(['3 4', '3 4', '2', '2'])
  })

  it('toneType: none', () => {
    expect(polyphonic('好好学习', { toneType: 'none' })).toEqual(['hao', 'hao', 'xue', 'xi'])
  })

  it('toneType: num', () => {
    expect(polyphonic('好好学习', { toneType: 'num' })).toEqual(['hao3 hao4', 'hao3 hao4', 'xue2', 'xi2'])
  })

  it('removeNonZh drops non-Chinese characters', () => {
    expect(polyphonic('好好学习s')).toEqual(['hǎo hào', 'hǎo hào', 'xué', 'xí', 's'])
    expect(polyphonic('好好学习s', { removeNonZh: true })).toEqual(['hǎo hào', 'hǎo hào', 'xué', 'xí'])
  })

  it('empty / non-string input', () => {
    expect(polyphonic('')).toEqual([])
    // @ts-ignore
    expect(polyphonic(11)).toEqual([])
  })
})
