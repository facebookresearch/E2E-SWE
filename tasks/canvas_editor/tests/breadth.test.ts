import { describe, it, expect, afterEach } from 'vitest'
import { ElementType, ControlType } from 'richdoc'
import { createEditor, main, findEl, type Ctx } from './_helpers'

let ctx: Ctx | undefined
afterEach(() => { ctx?.destroy(); ctx = undefined })
const ed = () => (ctx = createEditor()).editor

function textControl(conceptId: string) {
  return {
    type: ElementType.CONTROL,
    value: '',
    control: { type: ControlType.TEXT, conceptId, value: [], placeholder: 'name' }
  }
}

describe('breadth: controls / hyperlink / structural / export', () => {
  it('B1: text control value round-trips by conceptId', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertControl(textControl('c1'))
    e.command.executeSetControlValue({ conceptId: 'c1', value: 'Alice' })
    const gv = e.command.getControlValue({ conceptId: 'c1' })
    expect(gv[0].value).toBe('Alice')
    const ctl = findEl(e, (el: any) => el.type === 'control')
    expect(ctl.control.value).toEqual([{ value: 'Alice' }])
  })

  it('B2: getControlList reports the inserted controls by conceptId', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertControl(textControl('c1'))
    e.command.executeInsertControl(textControl('c2'))
    const list = e.command.getControlList()
    expect(list.length).toBe(2)
    expect(list.map((el: any) => el.control.conceptId).sort()).toEqual(['c1', 'c2'])
  })

  it('B3: hyperlink inserts a structured hyperlink element', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeHyperlink({ valueList: [{ value: 'Google' }], url: 'https://google.com' })
    const hl = findEl(e, (el: any) => el.type === 'hyperlink')
    expect(hl).toBeTruthy()
    expect(hl.url).toBe('https://google.com')
    expect(hl.valueList.map((v: any) => v.value).join('')).toBe('Google')
  })

  it('B5: separator is a structural element carrying its dash pattern', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeSeparator([])
    const sep = findEl(e, (el: any) => el.type === 'separator')
    expect(sep).toBeTruthy()
    expect(sep.dashArray).toEqual([])
  })

  it('B6: page break inserts a page-break element', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executePageBreak()
    const pb = findEl(e, (el: any) => el.type === 'pageBreak')
    expect(pb).toBeTruthy()
  })

  it('B7: getHTML serializes bold text with bold styling', () => {
    const e = ed()
    e.command.executeFocus()
    e.command.executeInsertElementList([{ value: 'hi' }])
    e.command.executeSelectAll(); e.command.executeBold()
    const html = e.command.getHTML().main.toLowerCase()
    expect(html).toMatch(/font-weight:\s*(bold|600|700)/)
  })
})
