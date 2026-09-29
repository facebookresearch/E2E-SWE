import { pinyin, segment, addDict, OutputFormat } from 'pinyinlib'
import { expect, describe, it } from 'vitest'

// The complete phrase dictionary is provided; load it so segmentation groups multi-char words.
const completeDict = require('@pinyin-pro/data/complete.json')
addDict(completeDict)

const SENT = '小明硕士毕业于中国科学院计算所，后在日本京都大学深造'

describe('segment', () => {
  it('PinyinString: groups words and joins their pinyin', () => {
    expect(segment(SENT, { format: OutputFormat.PinyinString })).toBe(
      'xiǎo míng shuòshì bìyè yú zhōngguókēxuéyuàn jìsuànsuǒ ， hòu zài rìběnjīngdūdàxué shēnzào',
    )
  })

  it('ZhSegment: returns the segmented Chinese words', () => {
    expect(segment(SENT, { format: OutputFormat.ZhSegment })).toEqual([
      '小', '明', '硕士', '毕业', '于', '中国科学院', '计算所', '，', '后', '在', '日本京都大学', '深造',
    ])
  })

  it('PinyinArray: per-word arrays of per-character pinyin', () => {
    expect(segment(SENT, { format: OutputFormat.PinyinArray })).toEqual([
      ['xiǎo'], ['míng'], ['shuò', 'shì'], ['bì', 'yè'], ['yú'],
      ['zhōng', 'guó', 'kē', 'xué', 'yuàn'], ['jì', 'suàn', 'suǒ'], ['，'],
      ['hòu'], ['zài'], ['rì', 'běn', 'jīng', 'dū', 'dà', 'xué'], ['shēn', 'zào'],
    ])
  })

  it('custom separator', () => {
    expect(segment(SENT, { format: OutputFormat.ZhString, separator: '/' })).toBe(
      '小/明/硕士/毕业/于/中国科学院/计算所/，/后/在/日本京都大学/深造',
    )
  })

  it('surname mode is honored during segmentation', () => {
    expect(segment('曾小贤你好', { mode: 'surname', format: OutputFormat.PinyinString })).toBe('zēng xiǎo xián nǐhǎo')
  })

  it('non-string input is returned unchanged', () => {
    // @ts-ignore
    expect(segment(123)).toBe(123)
  })

  it('all three segmentit algorithms produce the per-syllable reading', () => {
    const expected =
      'xiǎo míng shuò shì bì yè yú zhōng guó kē xué yuàn jì suàn suǒ ， hòu zài rì běn jīng dū dà xué shēn zào'
    expect(pinyin(SENT, { segmentit: 1 })).toBe(expected)
    expect(pinyin(SENT, { segmentit: 2 })).toBe(expected)
    expect(pinyin(SENT, { segmentit: 3 })).toBe(expected)
  })
})
