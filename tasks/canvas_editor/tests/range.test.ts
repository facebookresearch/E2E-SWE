import { describe, it, expect, afterEach } from 'vitest'
import { RowFlex, EditorZone } from 'richdoc'
import { createEditor, main, type Ctx } from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = (data?: any, opts?: any) => (ctx = createEditor(data, opts)).editor

describe('range / selection / zones / formatting', () => {
  it('R1: partial-selection bold splits the zipped run; selection is half-open [start,end)', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello' }])
    e.command.executeSetRange(1, 3)
    expect(e.command.getRangeText()).toBe('he')
    e.command.executeBold()
    expect(main(e)).toEqual([{ value: '\nhe', bold: true }, { value: 'llo' }])
  })

  it('R2: toggle-off requires full coverage (any-off => all-on, all-on => off)', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'abcd' }])
    e.command.executeSelectAll(); e.command.executeBold()
    expect(main(e).every((el: any) => el.bold === true)).toBe(true)
    e.command.executeSelectAll(); e.command.executeBold()
    expect(main(e).some((el: any) => el.bold === true)).toBe(false)
  })

  it('R3: collapsed-caret format is a no-op on the model', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hi' }])
    e.command.executeSetRange(2, 2)
    e.command.executeBold()
    expect(main(e)).toEqual([{ value: '\nhi' }])
  })

  it('R4: zone content isolation (header vs main)', () => {
    const e = ed({ header: [{ value: '\n' }], main: [{ value: '\n' }], footer: [{ value: '\n' }] })
    e.command.executeSetZone(EditorZone.HEADER)
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'HDR' }])
    e.command.executeSetZone(EditorZone.MAIN)
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'BODY' }])
    const t = e.command.getText()
    expect(t.header).toContain('HDR')
    expect(t.main).toContain('BODY')
    expect(t.main).not.toContain('HDR')
  })

  it('R5: index space is grapheme clusters (emoji = one index)', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'a😀bç' }])
    e.command.executeSetRange(2, 3)
    expect(e.command.getRangeText()).toBe('😀')
  })

  it('R6: color(null) deletes the key; color(value) sets it', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'x' }])
    e.command.executeSelectAll(); e.command.executeColor('#ff0000')
    expect(main(e)).toEqual([{ value: '\nx', color: '#ff0000' }])
    e.command.executeSelectAll(); e.command.executeColor(null)
    expect(main(e)).toEqual([{ value: '\nx' }])
  })

  it('R7: executeFormat clears char styles but keeps rowFlex', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'x' }])
    e.command.executeSelectAll(); e.command.executeBold(); e.command.executeRowFlex(RowFlex.CENTER)
    e.command.executeSelectAll(); e.command.executeFormat()
    const m = main(e)
    expect(m.some((el: any) => el.bold)).toBe(false)
    expect(m.some((el: any) => el.rowFlex === RowFlex.CENTER)).toBe(true)
  })

  it('R8: selection replacement via insertElementList', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello world' }])
    e.command.executeSetRange(1, 6)
    e.command.executeInsertElementList([{ value: 'HI' }])
    expect(e.command.getText().main).toBe('\nHI world')
  })

  it('R10: getRange + replaceRange round-trip a selection', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hello world' }])
    e.command.executeSetRange(1, 6)
    expect(e.command.getRangeText()).toBe('hello')
    const r = e.command.getRange()
    e.command.executeSetRange(0, 0)
    expect(e.command.getRangeText()).toBe('')
    e.command.executeReplaceRange(r)
    expect(e.command.getRangeText()).toBe('hello')
  })

  it('R9: underline toggles the underline field across the whole selection', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hi' }])
    e.command.executeSelectAll(); e.command.executeUnderline()
    expect(main(e)).toEqual([{ value: '\nhi', underline: true }])
  })
})
