/**
 * 数据集「批量导入」粘贴解析（纯函数，ImportSheetsDialog 的可测试内核）。
 *
 * 输入形态（2026-11-06 需求）：
 * - Excel 选中区域直接复制 → Tab 分隔（首选），首行通常是字段名
 *   （如 提单号/下单客户名称 → 每行一个 sheet，多变量组）
 * - CSV 文本（半角/全角逗号）
 * - 单列纯值列表（如一列提单号）——无表头，字段名由调用方给（弹窗预填
 *   现有 sheet 首字段，如 bl_no）
 *
 * 产出：headers（字段名）+ rows（每行 label=首列值、data=字段名→单元格字符串）。
 * 行序即 sheet 序；值一律字符串（与编辑器手输一致，${} 求值不区分类型）。
 */

export interface SheetPasteOptions {
  /** 多列时首行是否字段名（单列恒无表头，选项被忽略） */
  firstRowIsHeader: boolean
  /** 无表头时的字段名（单列场景；缺省 value）。多列无表头用 列1..列N */
  fallbackField?: string
}

export interface ParsedSheetRow {
  /** sheet 名（=首列值；空值由调用方补缺省） */
  label: string
  /** 字段名 → 单元格字符串（短行补空串） */
  data: Record<string, string>
}

export interface SheetPasteParse {
  /** 列数（≥1） */
  columns: number
  /** 实际字段名（表行或生成；已去重，空位补 列N） */
  headers: string[]
  rows: ParsedSheetRow[]
}

/** 分隔符探测：任一行含 Tab → TSV（Excel 复制）；否则含逗号（半/全角）→ CSV；否则单列 */
function detectSeparator(lines: string[]): string | null {
  if (lines.some((l) => l.includes('\t'))) return '\t'
  if (lines.some((l) => l.includes(',') || l.includes('，'))) return ','
  return null
}

function splitCells(line: string, sep: string | null): string[] {
  if (sep === null) return [line.trim()]
  if (sep === ',') line = line.replace(/，/g, ',')  // 全角逗号归一
  return line.split(sep).map((c) => c.trim())
}

/** 空表头位补 列N；重名追加序号（a、a2），保证 data 键唯一 */
function normalizeHeaders(raw: string[]): string[] {
  const out: string[] = []
  raw.forEach((h, i) => {
    let name = h || `列${i + 1}`
    if (out.includes(name)) {
      let n = 2
      while (out.includes(`${name}${n}`)) n++
      name = `${name}${n}`
    }
    out.push(name)
  })
  return out
}

export function parseSheetPaste(text: string, opts: SheetPasteOptions): SheetPasteParse {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+$/, ''))
    .filter((l) => l.trim() !== '')

  const sep = detectSeparator(lines)
  const allCells = lines.map((l) => splitCells(l, sep))
  // 全空行（分隔符但全空 cell）剔除
  const cellRows = allCells.filter((cells) => cells.some((c) => c !== ''))
  if (!cellRows.length) return { columns: 0, headers: [], rows: [] }

  if (sep === null) {
    // 单列：恒无表头，字段名 = fallbackField
    const field = (opts.fallbackField || '').trim() || 'value'
    return {
      columns: 1,
      headers: [field],
      rows: cellRows.map((cells) => ({
        label: cells[0],
        data: { [field]: cells[0] },
      })),
    }
  }

  const width = Math.max(...cellRows.map((c) => c.length))
  let headers: string[]
  let dataRows: string[][]
  if (opts.firstRowIsHeader && cellRows.length > 1) {
    headers = normalizeHeaders(cellRows[0])
    // 表头行窄于数据行时补齐（数据多出的列仍可承载）
    while (headers.length < width) headers.push(`列${headers.length + 1}`)
    dataRows = cellRows.slice(1)
  } else {
    headers = normalizeHeaders(Array.from({ length: width }, (_, i) => `列${i + 1}`))
    dataRows = cellRows
  }

  const rows: ParsedSheetRow[] = dataRows.map((cells) => {
    const data: Record<string, string> = {}
    headers.forEach((h, i) => { data[h] = cells[i] ?? '' })
    return { label: cells[0] ?? '', data }
  })
  return { columns: width, headers, rows }
}
