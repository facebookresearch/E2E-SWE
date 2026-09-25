import { getInitialAndFinal, getFinalParts, getNumOfTone } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// Pinyin-analysis helpers operating on a plain pinyin syllable string.
describe('getInitialAndFinal', () => {
  it('splits initial and final', () => {
    expect(getInitialAndFinal('shuang')).toEqual({ initial: 'sh', final: 'uang' })
    expect(getInitialAndFinal('lue')).toEqual({ initial: 'l', final: 'ue' })
    expect(getInitialAndFinal('xiong')).toEqual({ initial: 'x', final: 'iong' })
    expect(getInitialAndFinal('zhi')).toEqual({ initial: 'zh', final: 'i' })
  })

  it('zero-initial syllables have an empty initial', () => {
    expect(getInitialAndFinal('yuan')).toEqual({ initial: 'y', final: 'uan' })
    expect(getInitialAndFinal('er')).toEqual({ initial: '', final: 'er' })
  })

  it('a lone initial has an empty final', () => {
    expect(getInitialAndFinal('n')).toEqual({ initial: 'n', final: '' })
  })
})

describe('getFinalParts', () => {
  it('splits a final into head / body / tail', () => {
    expect(getFinalParts('hǎo')).toEqual({ head: '', body: 'ǎ', tail: 'o' })
    expect(getFinalParts('xué')).toEqual({ head: 'ü', body: 'é', tail: '' })
    expect(getFinalParts('xiàng')).toEqual({ head: 'i', body: 'à', tail: 'ng' })
    expect(getFinalParts('yuán')).toEqual({ head: 'u', body: 'á', tail: 'n' })
  })
})

describe('getNumOfTone', () => {
  it('returns the tone number (0 for neutral)', () => {
    expect(getNumOfTone('hǎo')).toBe('3')
    expect(getNumOfTone('xué')).toBe('2')
    expect(getNumOfTone('ma')).toBe('0')
  })
})
