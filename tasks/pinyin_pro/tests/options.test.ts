import { pinyin } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// The pinyin() option matrix. Medium weight — the option names are documented, but exact outputs of
// pattern/nonZh/type/v/multiple on non-obvious inputs are the graded behavior.
describe('pinyin options', () => {
  it('toneType: none / num', () => {
    expect(pinyin('汉语', { toneType: 'none' })).toBe('han yu')
    expect(pinyin('汉语', { toneType: 'num' })).toBe('han4 yu3')
  })

  it('type: array', () => {
    expect(pinyin('汉语', { type: 'array' })).toEqual(['hàn', 'yǔ'])
  })

  it('pattern: initial / final', () => {
    expect(pinyin('拼音', { pattern: 'initial' })).toBe('p y')
    expect(pinyin('拼音', { pattern: 'final' })).toBe('īn īn')
  })

  it('pattern: num / first', () => {
    expect(pinyin('拼音', { pattern: 'num' })).toBe('1 1')
    expect(pinyin('拼音', { pattern: 'first' })).toBe('p y')
  })

  it('pattern: finalBody / finalTail', () => {
    expect(pinyin('拼音', { pattern: 'finalBody' })).toBe('ī ī')
    expect(pinyin('拼音', { pattern: 'finalTail' })).toBe('n n')
  })

  it('nonZh: removed / consecutive / spaced', () => {
    expect(pinyin('中a文bc', { nonZh: 'removed' })).toBe('zhōng wén')
    expect(pinyin('中a文bc', { nonZh: 'consecutive' })).toBe('zhōng a wén bc')
    expect(pinyin('中a文bc', { nonZh: 'spaced' })).toBe('zhōng a wén b c')
  })

  it('v: renders ü as v', () => {
    expect(pinyin('吕布', { v: true })).toBe('lǚ bù')
  })

  it('multiple: all readings of a single character', () => {
    expect(pinyin('好', { multiple: true })).toBe('hǎo hào')
  })
})
