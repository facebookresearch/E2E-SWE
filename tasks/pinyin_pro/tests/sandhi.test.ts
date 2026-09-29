import { pinyin } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// Tone sandhi for 一 and 不 (ON by default). Heavily weighted — the exact rules (2nd tone before a
// 4th-tone syllable, 4th tone before others for 一, neutral tone between reduplication) are bespoke.
describe('tone sandhi (一 / 不)', () => {
  it('不 -> bú (2nd tone) before a 4th-tone syllable', () => {
    expect(pinyin('不是')).toBe('bú shì')
    expect(pinyin('不对')).toBe('bú duì')
  })

  it('不 stays bù before non-4th-tone syllables', () => {
    expect(pinyin('不好')).toBe('bù hǎo')
    expect(pinyin('不能')).toBe('bù néng')
  })

  it('一 -> yí (2nd tone) before a 4th-tone syllable', () => {
    expect(pinyin('一定')).toBe('yí dìng')
    expect(pinyin('一个')).toBe('yí gè')
    expect(pinyin('一样')).toBe('yí yàng')
  })

  it('一 -> yì (4th tone) before 1st/2nd/3rd-tone syllables', () => {
    expect(pinyin('一天')).toBe('yì tiān')
    expect(pinyin('一起')).toBe('yì qǐ')
  })

  it('一 / 不 become neutral tone between reduplicated verbs', () => {
    expect(pinyin('看一看')).toBe('kàn yi kàn')
    expect(pinyin('想不想')).toBe('xiǎng bu xiǎng')
  })

  it('toneSandhi:false keeps the base tones', () => {
    expect(pinyin('不是', { toneSandhi: false })).toBe('bù shì')
    expect(pinyin('一天', { toneSandhi: false })).toBe('yī tiān')
  })
})
