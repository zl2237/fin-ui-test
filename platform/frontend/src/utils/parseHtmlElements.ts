/**
 * HTML 片段 → 元素库导入候选（纯函数，DOMParser 解析，无副作用）。
 *
 * 场景：F12 → Copy outerHTML → 「HTML 导入」弹窗粘贴 → 解析出页面全部交互元素，
 * 人工勾选 / 改 key / 补中文描述后经 elementApi.batch 覆盖式入库。
 * 策略键与后端 ui_runtime._STRATEGY_PRIORITY 语义对齐（for=for 属性值、
 * placeholder 原样、button 保留内部空格、tab=DOM id），full_xpath 恒兜底。
 * 兼容粘贴 .vue 模板源码（识别 @click / v-on:click 行为节点）。
 */
import { toPinyinInitials } from './pinyin'

export type ElementCategory = 'input' | 'button' | 'other'
/** manual = locator JSON 等人工已命名来源（导入弹窗嗅探时构造，解析器本身不产出） */
export type KeyOrigin = 'testid' | 'name' | 'id' | 'pinyin' | 'hash' | 'manual'

export interface ParsedElement {
  /** 行唯一标识：预览表格行内会改 element_key，勾选跟踪必须用 uid */
  uid: number
  element_key: string
  description: string
  category: ElementCategory
  key_origin: KeyOrigin
  /** 语义定位策略（不含 full_xpath，后者恒定单独存） */
  strategies: Record<string, string>
  full_xpath: string
  /** 人读来源摘要（预览表格展示，辅助取舍） */
  source: string
  /** 与其他候选语义策略完全相同（如多行同名按钮），提示人工区分 */
  dup_strategy?: boolean
}

export interface ParseHtmlResult {
  ok: boolean
  error?: string
  elements: ParsedElement[]
  skipped: { hidden: number; display_only: number; merged: number }
}

// ---- 基础工具 ----

/** CSS 选择器 / xpath 锚点均安全的 id 形态 */
const SAFE_ID = /^[A-Za-z][A-Za-z0-9_-]*$/
/** 框架自动生成的 id（EP el-id-*、uuid、纯数字、超长 hex）：定位不稳定，不进策略也不用于命名 */
const GENERATED_ID = [
  /^\d+$/,
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  /^[0-9a-f]{16,}$/i,
  /^el-id-\d+/i,
]
/** Copy outerHTML 常带出的浮层/提示容器：整棵子树剔除 */
const NOISE_SEL =
  '.el-select-dropdown,.el-picker__popper,.el-tooltip__popper,.el-popper,.el-message,.el-notification'

const CHOICE_TYPES = new Set(['checkbox', 'radio'])
const BUTTON_INPUT_TYPES = new Set(['button', 'submit', 'reset'])

/** 空白折叠为单空格 + 去首尾（保留内部单空格，如若依「查 询」） */
function normText(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/** 表单 label 文本收尾：去尾冒号（中英文） */
function stripColon(s: string): string {
  return s.replace(/[：:]+$/, '').trim()
}

function isGeneratedId(id: string): boolean {
  return !id || id.length > 48 || GENERATED_ID.some((r) => r.test(id))
}

/** 可作为 #css 锚点的 id（存在且非生成式） */
function usableId(el: Element): string {
  const id = el.getAttribute('id') || ''
  return id && SAFE_ID.test(id) && !isGeneratedId(id) ? id : ''
}

/** camelCase / 任意标识 → snake_case（非法字符折叠为下划线） */
function snakeCase(s: string): string {
  return s
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^A-Za-z0-9_]+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase()
}

/** FNV-1a 32bit → base36 六位（full_xpath 稳定哈希，兜底命名用） */
function fnv1a36(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36).padStart(6, '0').slice(-6)
}

/**
 * 中文文本 → 拼音首字母 key 片段：仅当全部 CJK 命中 pinyin.ts 词表才采用
 * （未收录字会让首字母串缺位，半截拼音比哈希更误导，宁可直接回退 hash）。
 */
function cjkInitials(text: string): string {
  if (!text) return ''
  const cjk = Array.from(text).filter((ch) => /[一-鿿]/.test(ch))
  if (!cjk.length) return ''
  if (toPinyinInitials(cjk.join('')).length !== cjk.length) return ''
  return toPinyinInitials(text).replace(/[^a-zA-Z0-9]/g, '').toLowerCase().slice(0, 24)
}

/** 绝对 xpath：祖先遇可用 id 即锚定截断（`//*[@id='x']/div/input`），否则回 /html/body 全路径 */
function fullXPath(el: Element): string {
  const parts: string[] = []
  let cur: Element | null = el
  while (cur) {
    const tag = cur.tagName.toLowerCase()
    if (tag === 'html') break
    const uid = usableId(cur)
    if (uid) {
      parts.push(`*[@id='${uid}']`)
      return '//' + parts.reverse().join('/')
    }
    const parent: Element | null = cur.parentElement
    if (!parent) break
    const same = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName)
    const idx = same.indexOf(cur) + 1
    parts.push(same.length > 1 ? `${tag}[${idx}]` : tag)
    cur = parent
  }
  return '/html/' + parts.reverse().join('/')
}

/** 粘贴 DOM 无 computed style：只信行内 hidden 属性 / display:none / aria-hidden */
function isHiddenEl(el: Element): boolean {
  if (el.hasAttribute('hidden')) return true
  const style = (el.getAttribute('style') || '').replace(/\s/g, '')
  if (style.includes('display:none') || style.includes('visibility:hidden')) return true
  // 图标等装饰节点常标 aria-hidden；表单控件本体标 aria-hidden 的场景不剔除
  if (el.getAttribute('aria-hidden') === 'true' && !/^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(el.tagName)) {
    return true
  }
  return false
}

type Role = 'text-input' | 'choice' | 'clickable'

/** 交互角色判定：null = 非交互（继续下钻子节点） */
function roleOf(el: Element): Role | 'hidden' | null {
  const tag = el.tagName
  if (tag === 'INPUT') {
    const type = (el.getAttribute('type') || 'text').toLowerCase()
    if (type === 'hidden') return 'hidden'
    if (CHOICE_TYPES.has(type)) return 'choice'
    if (BUTTON_INPUT_TYPES.has(type)) return 'clickable'
    return 'text-input'
  }
  if (tag === 'TEXTAREA' || tag === 'SELECT') return 'text-input'
  if (tag === 'BUTTON') return 'clickable'
  const cls = el.classList
  if (cls.contains('el-button') || cls.contains('el-tabs__item') || el.getAttribute('role') === 'tab') {
    return 'clickable'
  }
  // .vue 模板源码（未渲染）：DOMParser 把指令保留为属性
  if (el.getAttribute('@click') || el.getAttribute('v-on:click')) return 'clickable'
  if (tag === 'A') {
    const t = normText(el.textContent || '')
    return t && t.length <= 30 ? 'clickable' : null // 短文本链接当按钮；长文本（正文链接）忽略
  }
  return null
}

/** 祖先 el-form-item 的 label 文本（Element 表单语义向容器借） */
function formItemLabel(el: Element): string {
  const item = el.closest('.el-form-item')
  if (!item) return ''
  for (const child of Array.from(item.children)) {
    if (child.classList.contains('el-form-item__label')) {
      return stripColon(normText(child.textContent || ''))
    }
  }
  return ''
}

/** checkbox/radio 的关联 label 文本：包裹 label 优先，其次 label[for=id] */
function choiceLabel(el: Element, forLabels: Map<string, Element>): string {
  const lab = el.closest('label')
  if (lab) return stripColon(normText(lab.textContent || ''))
  const id = el.getAttribute('id') || ''
  const fl = id ? forLabels.get(id) : undefined
  return fl ? stripColon(normText(fl.textContent || '')) : ''
}

/** 可点击元素文本：input[type=button] 取 value，其余取 textContent */
function clickText(el: Element): string {
  if (el.tagName === 'INPUT') return normText(el.getAttribute('value') || '')
  return normText(el.textContent || '')
}

interface Cand {
  el: Element
  role: Role
  category: ElementCategory
  strategies: Record<string, string>
  full_xpath: string
  namingText: string
  source: string
}

/** 从交互元素推导语义策略 + 命名/描述文本 + 来源摘要 */
function derive(el: Element, role: Role, forLabels: Map<string, Element>): Cand {
  const st: Record<string, string> = {}
  const testid = el.getAttribute('data-testid') || el.getAttribute('data-test') || ''
  if (testid) st.test_id = testid
  const idRaw = el.getAttribute('id') || ''
  const uid = usableId(el)
  const ph = el.getAttribute('placeholder') || ''
  const aria = el.getAttribute('aria-label') || ''
  const title = el.getAttribute('title') || ''
  let namingText = ''

  if (role === 'text-input') {
    const fl = forLabels.get(idRaw)
    if (fl) st.for = fl.getAttribute('for') || idRaw // for 策略值 = for 属性值（非 label 文本）
    const labelText = formItemLabel(el)
    if (labelText) st.label = labelText
    if (ph.trim()) st.placeholder = ph // 原样不截断（后端 exact 精确匹配）
    namingText = labelText || ph
  } else if (role === 'choice') {
    const boxLabel = choiceLabel(el, forLabels)
    if (boxLabel) st.checkbox = boxLabel
    namingText = boxLabel
  } else {
    const text = clickText(el)
    const isTab = el.classList.contains('el-tabs__item') || el.getAttribute('role') === 'tab'
    if (isTab) {
      if (idRaw) st.tab = idRaw // tab 策略值 = DOM id 原值（tab-xxx），非文本
      if (text) st.text = text
    } else if (el.tagName === 'A') {
      if (text) st.text = text
    } else if (text) {
      // 真按钮走 button 策略（get_by_role）；@click 的 span 等非按钮元素走 text
      if (el.tagName === 'BUTTON' || el.classList.contains('el-button')) st.button = text // 保留内部空格（若依「查 询」）
      else st.text = text
    } else if (aria || title) {
      st.text = aria || title
    }
    namingText = text || aria || title
  }
  if (uid) st.css = `#${uid}`

  const category: ElementCategory = role === 'text-input' ? 'input' : role === 'clickable' ? 'button' : 'other'
  return { el, role, category, strategies: st, full_xpath: fullXPath(el), namingText, source: buildSource(el, role, namingText) }
}

function buildSource(el: Element, role: Role, namingText: string): string {
  const parts = [el.tagName.toLowerCase() + (usableId(el) ? `#${usableId(el)}` : '')]
  const name = el.getAttribute('name')
  if (name) parts.push(`name=${name}`)
  if (namingText) parts.push(`「${namingText}」`)
  return parts.join(' ').slice(0, 80)
}

const PREFIX: Record<ElementCategory, string> = { input: 'inp', button: 'btn', other: 'el' }

/**
 * 解析 HTML 片段，产出元素库导入候选。
 * - 提取白名单：文本输入（input/textarea/select，含 el-select 只读占位）、
 *   按钮/链接/tab、checkbox/radio、@click 行为节点
 * - 剔除：hidden/display:none/aria-hidden、浮层容器（下拉/日期弹层/tooltip/消息条）
 * - 折叠：同一日期范围编辑器（.el-date-editor/.el-range-editor）内的多个 input 合并 1 条
 */
export function parseHtmlElements(html: string): ParseHtmlResult {
  const skipped = { hidden: 0, display_only: 0, merged: 0 }
  const fail = (error: string): ParseHtmlResult => ({ ok: false, error, elements: [], skipped })

  if (!html || !html.trim()) return fail('请先粘贴页面 HTML')

  let doc: Document
  try {
    doc = new DOMParser().parseFromString(html, 'text/html')
  } catch {
    return fail('HTML 解析失败，请粘贴页面片段原文')
  }
  const root = doc.body
  if (!root) return fail('未解析到页面内容')

  // 原生表单关联表：input id → label[for=id] 元素
  const forLabels = new Map<string, Element>()
  for (const lab of root.querySelectorAll('label[for]')) {
    const f = lab.getAttribute('for') || ''
    if (f && !forLabels.has(f)) forLabels.set(f, lab)
  }

  // ---- 深度优先收集交互候选（噪声/隐藏子树整枝剪掉） ----
  const cands: Cand[] = []
  const walk = (el: Element): void => {
    // .vue 模板源码：<template> 的子节点在 content 分片里，不在 children
    if (el.tagName === 'TEMPLATE' && (el as HTMLTemplateElement).content) {
      for (const child of Array.from((el as HTMLTemplateElement).content.children)) walk(child)
      return
    }
    if (el.matches(NOISE_SEL)) {
      skipped.display_only++
      return
    }
    if (isHiddenEl(el)) {
      skipped.hidden++
      return
    }
    const role = roleOf(el)
    if (role === 'hidden') {
      skipped.hidden++
      return
    }
    if (role) cands.push(derive(el, role, forLabels))
    for (const child of Array.from(el.children)) walk(child)
  }
  // .vue 模板源码的顶层 <template> 会被解析进 head——head/body 都要扫
  for (const child of [...Array.from(doc.head.children), ...Array.from(root.children)]) walk(child)

  // ---- 日期范围折叠：同一范围编辑器内多个 input 只留第 1 个 ----
  const rangeGroups = new Map<Element, number[]>()
  cands.forEach((c, i) => {
    if (c.role !== 'text-input') return
    const rc = c.el.closest('.el-date-editor, .el-range-editor')
    if (!rc) return
    const arr = rangeGroups.get(rc) || []
    arr.push(i)
    rangeGroups.set(rc, arr)
  })
  const drop = new Set<number>()
  for (const idxs of rangeGroups.values()) {
    if (idxs.length < 2) continue
    idxs.slice(1).forEach((i) => drop.add(i))
    skipped.merged += idxs.length - 1
  }
  const kept = cands.filter((_, i) => !drop.has(i))

  // ---- 语义策略完全相同的候选互标（表格多行同名按钮等） ----
  const sigCount = new Map<string, number>()
  const sigOf = (c: Cand) =>
    Object.keys(c.strategies).length
      ? JSON.stringify(Object.entries(c.strategies).sort(([a], [b]) => (a < b ? -1 : 1)))
      : ''
  for (const c of kept) {
    const sig = sigOf(c)
    if (sig) sigCount.set(sig, (sigCount.get(sig) || 0) + 1)
  }

  // ---- 命名链：testid → name → id（剔生成式）→ 拼音首字母 → 类别前缀+路径哈希 ----
  const used = new Set<string>()
  const unique = (base: string): string => {
    let k = base
    let i = 2
    while (used.has(k)) k = `${base}_${i++}`
    used.add(k)
    return k
  }

  const elements: ParsedElement[] = kept.map((c) => {
    const el = c.el
    const testid = el.getAttribute('data-testid') || el.getAttribute('data-test') || ''
    const nameAttr = el.getAttribute('name') || ''
    let key = ''
    let origin: KeyOrigin = 'hash'
    if (snakeCase(testid)) {
      key = snakeCase(testid)
      origin = 'testid'
    } else if (snakeCase(nameAttr)) {
      key = snakeCase(nameAttr)
      origin = 'name'
    } else if (snakeCase(usableId(el))) {
      key = snakeCase(usableId(el))
      origin = 'id'
    } else {
      const p = cjkInitials(c.namingText)
      if (p) {
        key = `${PREFIX[c.category]}_${p}`
        origin = 'pinyin'
      } else {
        key = `${PREFIX[c.category]}_el${fnv1a36(c.full_xpath)}`
      }
    }
    const sig = sigOf(c)
    return {
      uid: 0,
      element_key: unique(key),
      description: c.namingText,
      category: c.category,
      key_origin: origin,
      strategies: c.strategies,
      full_xpath: c.full_xpath,
      source: c.source,
      dup_strategy: sig ? (sigCount.get(sig) || 0) > 1 : undefined,
    }
  })
  elements.forEach((e, i) => (e.uid = i + 1))

  if (!elements.length && !skipped.hidden && !skipped.display_only && !skipped.merged) {
    return fail('未识别到交互元素，请粘贴页面 HTML（F12 → 元素面板 → Copy outerHTML）')
  }
  return { ok: true, elements, skipped }
}
