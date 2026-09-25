import { pinyin } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// Surname mode: prefer surname-specific readings for characters in the surname table. Heavily
// weighted — the surname readings + off/all/head scoping are bespoke and not derivable from generic
// pinyin knowledge.
describe('surname mode', () => {
  it('compound surname 万俟 -> mò qí', () => {
    expect(pinyin('万俟', { mode: 'surname' })).toBe('mò qí')
  })

  it('compound surname 令狐 in a sentence', () => {
    expect(pinyin('我叫令狐冲', { mode: 'surname' })).toBe('wǒ jiào líng hú chōng')
  })

  it('曾 as a surname -> zēng', () => {
    expect(pinyin('曾令狐冲', { mode: 'surname' })).toBe('zēng líng hú chōng')
  })

  it('区 as a surname -> ōu', () => {
    expect(pinyin('我叫区中青', { mode: 'surname' })).toBe('wǒ jiào ōu zhōng qīng')
  })

  it('surname: head applies only at the start of the string', () => {
    expect(pinyin('曾乐乐', { mode: 'surname', surname: 'head' })).toBe('zēng lè lè')
  })

  it('surname: head auto-detects a leading compound surname', () => {
    expect(pinyin('令狐冲', { surname: 'head' })).toBe('líng hú chōng')
    expect(pinyin('万俟英', { surname: 'head' })).toBe('mò qí yīng')
  })
})
