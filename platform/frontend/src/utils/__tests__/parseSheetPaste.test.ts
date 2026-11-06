import { describe, expect, it } from 'vitest'
import { parseSheetPaste } from '../parseSheetPaste'

describe('parseSheetPaste（数据集批量导入粘贴解析）', () => {
  it('TSV 带表头：Excel 复制多列，首行=字段名，每行一个 sheet', () => {
    const r = parseSheetPaste('提单号\t下单客户名称\nBL1\t客户A\nBL2\t客户B', {
      firstRowIsHeader: true,
    })
    expect(r.columns).toBe(2)
    expect(r.headers).toEqual(['提单号', '下单客户名称'])
    expect(r.rows).toHaveLength(2)
    expect(r.rows[0]).toEqual({
      label: 'BL1',
      data: { 提单号: 'BL1', 下单客户名称: '客户A' },
    })
    expect(r.rows[1].label).toBe('BL2')
  })

  it('单列纯值：无表头，字段名取 fallbackField（如 bl_no），label=值本身', () => {
    const r = parseSheetPaste('BL1\nBL2\nBL3', {
      firstRowIsHeader: true, // 单列忽略该选项
      fallbackField: 'bl_no',
    })
    expect(r.columns).toBe(1)
    expect(r.headers).toEqual(['bl_no'])
    expect(r.rows.map((x) => x.label)).toEqual(['BL1', 'BL2', 'BL3'])
    expect(r.rows[2].data).toEqual({ bl_no: 'BL3' })
  })

  it('全角逗号 CSV 与半角逗号等价处理', () => {
    const r = parseSheetPaste('a，b\n1，2', { firstRowIsHeader: true })
    expect(r.headers).toEqual(['a', 'b'])
    expect(r.rows[0].data).toEqual({ a: '1', b: '2' })
  })

  it('多列无表头：字段名生成 列1..列N，全部行都是数据', () => {
    const r = parseSheetPaste('BL1\t客户A', { firstRowIsHeader: false })
    expect(r.headers).toEqual(['列1', '列2'])
    expect(r.rows).toHaveLength(1)
    expect(r.rows[0].data).toEqual({ 列1: 'BL1', 列2: '客户A' })
  })

  it('表头位空/重名：补 列N 与序号去重，data 键唯一', () => {
    const r = parseSheetPaste('a\t\ta\n1\t2\t3', { firstRowIsHeader: true })
    expect(r.headers).toEqual(['a', '列2', 'a2'])
    expect(r.rows[0].data).toEqual({ a: '1', 列2: '2', a2: '3' })
  })

  it('短行补空串、超宽表头补列；空行/空白行剔除；CRLF 兼容', () => {
    const r = parseSheetPaste('h1\th2\th3\r\n\r\nV1\r\n  \r\nV2\tV2b\n', {
      firstRowIsHeader: true,
    })
    expect(r.rows).toHaveLength(2)
    expect(r.rows[0].data).toEqual({ h1: 'V1', h2: '', h3: '' })
    expect(r.rows[1].label).toBe('V2')
  })

  it('仅一行且声明有表头：视为数据行（无表头可消费），字段名生成', () => {
    const r = parseSheetPaste('BL1\t客户A', { firstRowIsHeader: true })
    expect(r.headers).toEqual(['列1', '列2'])
    expect(r.rows).toHaveLength(1)
  })

  it('空输入：columns=0、rows 空', () => {
    expect(parseSheetPaste('\n \r\n', { firstRowIsHeader: true })).toEqual({
      columns: 0,
      headers: [],
      rows: [],
    })
  })
})
