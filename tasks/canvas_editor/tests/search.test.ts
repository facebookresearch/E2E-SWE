import { describe, it, expect, afterEach } from 'vitest'
import { createEditor, main, type Ctx } from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = (data?: any, opts?: any) => (ctx = createEditor(data, opts)).editor

describe('search / replace', () => {
  it('S1: replace inherits the first matched character’s formatting', () => {
    const e = ed({ header: [], main: [{ value: 'w', bold: true }, { value: 'orld' }], footer: [] })
    e.command.executeFocus()
    e.command.executeSearch('world')
    e.command.executeReplace('planet')
    const m = main(e)
    expect(e.command.getText().main).toContain('planet')
    // every element carrying replacement text is bold
    expect(m.filter((el: any) => /[planet]/.test(el.value)).every((el: any) => el.bold === true)).toBe(true)
  })

  it('S2: regex matches count by actual length, not pattern length', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hi hello hey' }])
    e.command.executeSearch('h\\w+', { isRegEnable: true })
    expect(e.command.getSearchNavigateInfo().count).toBe(3)
    const ranges = e.command.getKeywordRangeList('h\\w+')
    expect(ranges.length).toBe(3)
    // each match spans its own actual length (hi/hey/hello differ), not a fixed pattern length.
    // Three mutually distinct spans prove length-based grouping; the gaps between the sorted match
    // grapheme lengths (2/3/5 -> gaps 1,2) are endpoint-convention-independent (they hold identically
    // for the half-open [start,end) and the inclusive-endIndex conventions), so this also rejects
    // distinct-but-mis-measured spans while leaving the endpoint convention itself open.
    const spans = ranges.map((r: any) => r.endIndex - r.startIndex).sort((a: number, b: number) => a - b)
    expect(new Set(spans).size).toBe(3)
    expect(spans[1] - spans[0]).toBe(1)
    expect(spans[2] - spans[1]).toBe(2)
  })

  it('S3: single-occurrence replace via option.index', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a b a b a' }])
    e.command.executeSearch('a')
    e.command.executeReplace('X', { index: 1 })
    expect(e.command.getText().main).toBe('\na b X b a')
  })

  it('S4: replace-all with a length-changing replacement stays aligned', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'catcatcat' }])
    e.command.executeSearch('cat')
    e.command.executeReplace('tiger')
    expect(e.command.getText().main).toBe('\ntigertigertiger')
  })

  it('S5: empty-string replace deletes all matches', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'foo bar foo' }])
    e.command.executeSearch('foo')
    e.command.executeReplace('')
    expect(e.command.getText().main).toBe('\n bar ')
  })

  it('S6: case-sensitivity toggle changes the match count', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'Cat cat CAT' }])
    e.command.executeSearch('cat')
    expect(e.command.getKeywordRangeList('cat').length).toBe(3)
    e.command.executeSearch('cat', { isIgnoreCase: false })
    expect(e.command.getSearchNavigateInfo().count).toBe(1)
  })

  it('S7: navigate wraps around with 1-based index', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a a a' }])
    e.command.executeSearch('a')
    const seq: number[] = []
    e.command.executeSearchNavigateNext(); seq.push(e.command.getSearchNavigateInfo().index)
    e.command.executeSearchNavigateNext(); seq.push(e.command.getSearchNavigateInfo().index)
    e.command.executeSearchNavigateNext(); seq.push(e.command.getSearchNavigateInfo().index)
    e.command.executeSearchNavigateNext(); seq.push(e.command.getSearchNavigateInfo().index)
    e.command.executeSearchNavigatePre(); seq.push(e.command.getSearchNavigateInfo().index)
    expect(seq).toEqual([1, 2, 3, 1, 3])
  })

  it('S8: search counts CJK matches by grapheme (multilingual)', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: '中文搜索测试中文' }])
    expect(e.command.getKeywordRangeList('中文').length).toBe(2)
  })
})
