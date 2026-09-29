import { match } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// Fuzzy pinyin search: returns the matched character indices (or null). Heavily weighted — this API
// and its precision/continuous/space/lastPrecision/insensitive semantics are bespoke to the library.
describe('match', () => {
  it('default (non-continuous initials)', () => {
    expect(match('欢迎使用汉语拼音', 'hy')).toEqual([0, 1])
  })

  it('uncontinuous full syllables', () => {
    expect(match('汉语拼音', 'hanpin')).toEqual([0, 2])
  })

  it('all four syllables', () => {
    expect(match('汉语拼音', 'hyupy')).toEqual([0, 1, 2, 3])
  })

  it('precision start + continuous', () => {
    expect(match('欢迎使用汉语拼音', 'yingshyon', { precision: 'start', continuous: true })).toEqual([1, 2, 3])
  })

  it('precision any', () => {
    expect(match('开会', 'kaiui', { precision: 'any' })).toEqual([0, 1])
  })

  it('precision any across non-han + spaces', () => {
    expect(match('开      会s  啊', 'kaiuisa', { precision: 'any' })).toEqual([0, 7, 8, 11])
  })

  it('double-unicode: surrogate-pair char is skipped, indices stay correct', () => {
    expect(match('𧒽测试', 'cs')).toEqual([2, 3])
  })

  it('double-unicode + space', () => {
    expect(match('𧒽测 试', 'c s')).toEqual([2, 4])
  })

  it('lastPrecision every: success only when the last char is fully typed', () => {
    expect(match('汉语拼音', 'hanyupinyin', { lastPrecision: 'every' })).toEqual([0, 1, 2, 3])
    expect(match('汉语拼音', 'hanyupinyi', { lastPrecision: 'every' })).toEqual(null)
  })

  it('lastPrecision any', () => {
    expect(match('汉语拼音', 'hanyupini', { lastPrecision: 'any' })).toEqual([0, 1, 2, 3])
  })

  it('space ignore vs preserve', () => {
    expect(match('汉语 拼音', 'hanyu pini', { lastPrecision: 'any', space: 'ignore' })).toEqual([0, 1, 3, 4])
    expect(match('汉语 拼音', 'hanyu pini', { lastPrecision: 'any', space: 'preserve' })).toEqual([0, 1, 2, 3, 4])
  })

  it('case-insensitive by default; insensitive:false fails on case mismatch', () => {
    expect(match('汉语KK拼音', 'hanyukkpinyin')).toEqual([0, 1, 2, 3, 4, 5])
    expect(match('汉语KK拼音', 'hanyukkpinyin', { insensitive: false })).toEqual(null)
  })

  it('v option matches ü as v', () => {
    expect(match('我是吕布', 'woshilvbu', { v: true })).toEqual([0, 1, 2, 3])
  })

  it('returns null when the query cannot match', () => {
    expect(match('开会', 'kaig')).toEqual(null)
    expect(match('开会', 'l')).toEqual(null)
  })
})
