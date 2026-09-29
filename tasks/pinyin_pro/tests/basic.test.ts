import { pinyin } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// Light spot-checks of the default conversion path (de-weighted — this behavior is derivable from the
// provided dictionary; the harder behaviors are covered in the other suites).
describe('basic conversion', () => {
  it('converts a phrase to space-separated toned pinyin', () => {
    expect(pinyin('汉语拼音')).toBe('hàn yǔ pīn yīn')
  })

  // No `nonZh` passed: pins the documented default ('spaced') and a leading/trailing non-Chinese run,
  // neither of which the explicitly-optioned options.test.ts cases exercise.
  it('leaves non-Chinese characters in place by default', () => {
    expect(pinyin('a汉b')).toBe('a hàn b')
  })
})
