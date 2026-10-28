import { describe, it, expect } from 'vitest'
import { parseHtmlElements, type ParsedElement } from '../parseHtmlElements'

/** 按元素 key 取解析结果（断言用） */
function byKey(elements: ParsedElement[], key: string): ParsedElement {
  const hit = elements.find((e) => e.element_key === key)
  if (!hit) throw new Error(`未找到 key=${key}，现有：${elements.map((e) => e.element_key).join(', ')}`)
  return hit
}

/** 典型 ElementPlus 表单片段（若依系）：覆盖提取白名单 / 折叠 / 剔除全场景 */
const FORM_HTML = `
<div id="app">
  <form class="el-form">
    <div class="el-form-item">
      <label class="el-form-item__label">提单号：</label>
      <div class="el-form-item__content">
        <div class="el-input"><input type="text" name="blNo" class="el-input__inner" placeholder="请输入提单号"></div>
      </div>
    </div>
    <div class="el-form-item">
      <label class="el-form-item__label">船名</label>
      <div class="el-form-item__content">
        <div class="el-select">
          <input type="text" readonly="readonly" placeholder="请选择船名" class="el-input__inner">
        </div>
      </div>
    </div>
    <div class="el-form-item">
      <label class="el-form-item__label">装船期</label>
      <div class="el-form-item__content">
        <div class="el-date-editor el-date-editor--daterange">
          <input class="el-input__inner" placeholder="开始日期">
          <span class="el-range-separator">至</span>
          <input class="el-input__inner" placeholder="结束日期">
        </div>
      </div>
    </div>
    <label class="el-checkbox">
      <input type="checkbox" class="el-checkbox__input">
      <span class="el-checkbox__label">无供应商</span>
    </label>
    <input type="hidden" name="csrfToken">
    <button type="button" class="el-button el-button--primary"><span>查 询</span></button>
    <button type="button" class="el-button"><span>重 置</span></button>
  </form>
  <div class="el-tabs__nav">
    <div id="tab-first" role="tab" class="el-tabs__item">基本信息</div>
  </div>
</div>`

describe('parseHtmlElements', () => {
  it('空输入 ok=false', () => {
    const r = parseHtmlElements('   ')
    expect(r.ok).toBe(false)
    expect(r.error).toBeTruthy()
  })

  it('纯文本/无可交互元素 ok=false', () => {
    const r = parseHtmlElements('<div><p>一段说明文字</p></div>')
    expect(r.ok).toBe(false)
  })

  it('name 属性命名：camelCase → snake_case，label 策略取 form-item 文本去尾冒号', () => {
    const r = parseHtmlElements(FORM_HTML)
    expect(r.ok).toBe(true)
    const el = byKey(r.elements, 'bl_no')
    expect(el.key_origin).toBe('name')
    expect(el.strategies.label).toBe('提单号')
    expect(el.strategies.placeholder).toBe('请输入提单号')
    expect(el.description).toBe('提单号')
    expect(el.full_xpath).toBeTruthy()
  })

  it('el-select 只读占位 input 也算输入类，placeholder 原样保留，命名取 label 拼音', () => {
    const r = parseHtmlElements(FORM_HTML)
    const el = byKey(r.elements, 'inp_cm')
    expect(el.strategies.placeholder).toBe('请选择船名')
    expect(el.strategies.label).toBe('船名')
  })

  it('日期范围双 input 折叠为 1 条并计 merged，label 归属 form-item', () => {
    const r = parseHtmlElements(FORM_HTML)
    expect(r.skipped.merged).toBe(1)
    const range = r.elements.filter((e) => e.strategies.label === '装船期')
    expect(range).toHaveLength(1)
    expect(range[0].element_key).toBe('inp_zcq')
    expect(range[0].key_origin).toBe('pinyin')
  })

  it('checkbox 归 other 类，策略取包裹 label 文本', () => {
    const r = parseHtmlElements(FORM_HTML)
    const el = byKey(r.elements, 'el_wgys')
    expect(el.category).toBe('other')
    expect(el.strategies.checkbox).toBe('无供应商')
  })

  it('hidden input 剔除并计数', () => {
    const r = parseHtmlElements(FORM_HTML)
    expect(r.skipped.hidden).toBe(1)
    expect(r.elements.some((e) => e.strategies.name === 'csrfToken')).toBe(false)
  })

  it('按钮文本保留内部空格（若依「查 询」），词表未收录字回退 hash 命名', () => {
    const r = parseHtmlElements(FORM_HTML)
    const btns = r.elements.filter((e) => e.category === 'button' && e.strategies.button)
    expect(btns.map((e) => e.strategies.button)).toEqual(['查 询', '重 置'])
    // 「询」「置」未收录于 pinyin.ts 词表 → 半截拼音不可靠，回退路径哈希
    expect(btns.every((e) => e.key_origin === 'hash' && /^btn_el[a-z0-9]{6}$/.test(e.element_key))).toBe(true)
  })

  it('el-tabs__item 的 tab 策略 = DOM id 原值（非文本）', () => {
    const r = parseHtmlElements(FORM_HTML)
    const el = r.elements.find((e) => e.strategies.tab === 'tab-first')
    expect(el).toBeTruthy()
    expect(el!.strategies.text).toBe('基本信息')
    expect(el!.category).toBe('button')
  })

  it('full_xpath 遇可用 id 祖先即锚定（//*[@id=…] 起头）', () => {
    const r = parseHtmlElements(FORM_HTML)
    expect(byKey(r.elements, 'bl_no').full_xpath).toMatch(/^\/\/\*\[@id='app'\]\//)
  })

  it('裸 input 无任何语义线索：回退 hash 命名且两次解析稳定', () => {
    const html = '<div><input type="text"></div>'
    const r1 = parseHtmlElements(html)
    const r2 = parseHtmlElements(html)
    expect(r1.elements).toHaveLength(1)
    const e1 = r1.elements[0]
    expect(e1.key_origin).toBe('hash')
    expect(e1.element_key).toMatch(/^inp_el[a-z0-9]{6}$/)
    expect(Object.keys(e1.strategies)).toHaveLength(0)
    expect(e1.full_xpath).toBe(r2.elements[0].full_xpath)
    expect(e1.element_key).toBe(r2.elements[0].element_key)
  })

  it('原生 label[for]：for 策略 = for 属性值，css=#id，id 参与命名', () => {
    const html = `<form>
      <label for="userName">用户名</label>
      <input id="userName" type="text" placeholder="请输入用户名">
    </form>`
    const r = parseHtmlElements(html)
    const el = byKey(r.elements, 'user_name')
    expect(el.strategies.for).toBe('userName')
    expect(el.strategies.css).toBe('#userName')
    expect(el.strategies.placeholder).toBe('请输入用户名')
    expect(el.key_origin).toBe('id')
  })

  it('data-testid 最优先命名与策略', () => {
    const html = '<input type="text" data-testid="submitEmailInput">'
    const r = parseHtmlElements(html)
    const el = byKey(r.elements, 'submit_email_input')
    expect(el.key_origin).toBe('testid')
    expect(el.strategies.test_id).toBe('submitEmailInput')
  })

  it('同名 key 撞名自动递增 _2', () => {
    const html = `<div>
      <input type="text" name="blNo" placeholder="提单号">
      <input type="text" name="blNo" placeholder="提单号">
    </div>`
    const r = parseHtmlElements(html)
    expect(r.elements.map((e) => e.element_key)).toEqual(['bl_no', 'bl_no_2'])
  })

  it('语义策略完全相同的候选互标 dup_strategy（多行同名按钮）', () => {
    const html = `<div>
      <button type="button">保存</button>
      <button type="button">保存</button>
    </div>`
    const r = parseHtmlElements(html)
    expect(r.elements.map((e) => e.dup_strategy)).toEqual([true, true])
    // 撞名递增与 dup 标记并存
    expect(r.elements.map((e) => e.element_key)).toEqual(['btn_bc', 'btn_bc_2'])
  })

  it('浮层容器整棵剔除（Copy outerHTML 带出的下拉选项）', () => {
    const html = `<div>
      <input type="text" placeholder="请选择船名">
      <div class="el-select-dropdown"><ul><li>选项一</li><li>选项二</li></ul></div>
    </div>`
    const r = parseHtmlElements(html)
    expect(r.skipped.display_only).toBe(1)
    expect(r.elements).toHaveLength(1)
  })

  it('display:none / hidden 属性子树剔除', () => {
    const html = `<div>
      <input type="text" placeholder="可见输入">
      <div style="display: none;"><input type="text" placeholder="隐藏输入"></div>
      <div hidden><button>隐藏按钮</button></div>
    </div>`
    const r = parseHtmlElements(html)
    expect(r.elements).toHaveLength(1)
    expect(r.skipped.hidden).toBe(2)
  })

  it('.vue 模板源码：@click 行为节点识别为按钮，text 策略', () => {
    const html = `<template>
      <div>
        <span @click="addRow">新增行</span>
      </div>
    </template>`
    const r = parseHtmlElements(html)
    expect(r.elements).toHaveLength(1)
    expect(byKey(r.elements, 'btn_xzx').strategies.text).toBe('新增行')
  })

  it('框架生成式 id（el-id-*）不进策略也不参与命名', () => {
    const html = `<div class="el-form-item">
      <label class="el-form-item__label">提单号：</label>
      <input type="text" id="el-id-9123-3" placeholder="请输入提单号">
    </div>`
    const r = parseHtmlElements(html)
    const el = byKey(r.elements, 'inp_tdh')
    expect(el.strategies.css).toBeUndefined()
    expect(el.strategies.label).toBe('提单号')
    expect(el.key_origin).toBe('pinyin')
  })

  it('拼音词表未收录字：放弃半截拼音回退 hash', () => {
    // 「称」未收录于 pinyin.ts 词表
    const html = `<div class="el-form-item">
      <label class="el-form-item__label">客户名称：</label>
      <input type="text" placeholder="请输入客户名称">
    </div>`
    const r = parseHtmlElements(html)
    const el = r.elements[0]
    expect(el.key_origin).toBe('hash')
    expect(el.strategies.label).toBe('客户名称')
  })
})
