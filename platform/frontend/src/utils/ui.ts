/**
 * UI 纯函数：菜单激活解析、防抖、UI 动作词表。
 * 供 MainLayout（侧边栏激活态）、各列表页（搜索范式统一）、
 * 用例编排/节点配置/执行报告（UI 动作中文名）复用。
 */

/**
 * UI 动作词表：与后端 ui_runtime.py 动作词表对齐（原生 11 + 封装 12，共 23 种；
 * 其中 custom 为 JS 模板步骤占位，模板实体经动作库 custom_actions 维护）。
 * name 为中文名（节点/步骤显示），desc 为面板说明文案；
 * params 为参数解析（帮助中心「动作解析」tab 展示，与后端实现对齐）。
 */
export interface UiActionParam {
  name: string
  desc: string
  required?: boolean
}
/** 动作来源：native=Playwright 原生 API 直映射 / wrapped=非原生（组件增强、base 封装、实测沉淀、自定义模板） */
export type UiActionOrigin = 'native' | 'wrapped'
export interface UiActionMeta {
  action: string
  name: string
  desc: string
  origin: UiActionOrigin
  params?: UiActionParam[]
}
/** 来源元信息（帮助中心分组与下拉标签共用；分组计数按词表实时计算） */
export const UI_ACTION_ORIGINS: Record<UiActionOrigin, { label: string; group: string; note: string }> = {
  native: { label: '原生', group: 'Playwright 原生', note: '一个动作对应一个 Playwright 原生 API，行为与官方一致' },
  wrapped: { label: '封装', group: '非原生（封装/增强/自定义）', note: '在原生 API 之上封装：Element 组件适配、原框架 base 迁移、全链实测沉淀与自定义动作模板' },
}
export const UI_ACTIONS: UiActionMeta[] = [
  { action: 'goto', name: '导航', desc: '打开页面 URL（相对路径自动拼环境 base_url）', origin: 'native',
    params: [
      { name: 'url', desc: '页面地址，支持 ${变量}；不以 http 开头时自动拼环境 base_url', required: true },
      { name: 'wait_for', desc: '加载条件：load（默认）/ domcontentloaded / networkidle' },
      { name: 'timeout_ms', desc: '超时上限，默认 15000' },
    ] },
  { action: 'click', name: '点击', desc: '点击页面元素（JS 模式绕过可点击性校验，覆盖原 js_click）', origin: 'native',
    params: [
      { name: 'element', desc: '元素库引用（element_id）或自定义定位（strategy+value）', required: true },
      { name: 'mode', desc: 'default 普通点击（默认）/ js JS 直调（被遮挡/固定列副本区/动画中元素，原 js_click）' },
      { name: 'force', desc: 'true 时跳过可见性/可点击性校验（普通模式下生效）' },
    ] },
  { action: 'fill', name: '输入', desc: '向输入框填入文本（程序化赋值，速度快）', origin: 'native',
    params: [
      { name: 'element', desc: '目标输入框', required: true },
      { name: 'value', desc: '填入文本，支持 ${变量}', required: true },
    ] },
  { action: 'pick', name: '下拉选择(增强)', desc: 'Element 下拉：输入检索词并点选选项，自动校验选中值（防"看似选中实则未生效"）', origin: 'wrapped',
    params: [
      { name: 'element', desc: '目标下拉框', required: true },
      { name: 'value', desc: '选项文本（双向包含容差校验），支持 ${变量}', required: true },
    ] },
  { action: 'select_option', name: '下拉选择(原生)', desc: '原生 select 选值（单选/多选）', origin: 'native',
    params: [
      { name: 'element', desc: '目标原生 select', required: true },
      { name: 'value / values', desc: 'option 的 value（非显示文本），支持多选', required: true },
    ] },
  { action: 'check', name: '勾选', desc: '勾选/取消勾选复选框', origin: 'native',
    params: [
      { name: 'element', desc: '目标复选框', required: true },
      { name: 'value', desc: 'true 勾选（默认）/ false 取消勾选' },
    ] },
  { action: 'press', name: '按键', desc: '按键（可针对元素或整页）', origin: 'native',
    params: [
      { name: 'value', desc: '键名，如 Enter / Control+A，默认 Enter', required: true },
      { name: 'element', desc: '可选；定位元素时按键作用于该元素，否则作用于整页' },
    ] },
  { action: 'type', name: '键盘输入', desc: '模拟真实敲键逐字输入（自定义组件无视程序化赋值时使用）', origin: 'native',
    params: [
      { name: 'element', desc: '目标输入框（先点击聚焦再逐字敲入）', required: true },
      { name: 'value', desc: '逐字输入的内容，支持 ${变量}', required: true },
    ] },
  { action: 'date', name: '日期时间', desc: '日期时间选择器：填值并回车确认（复刻 base_page.timepicker）', origin: 'wrapped',
    params: [
      { name: 'element', desc: '目标日期选择器', required: true },
      { name: 'value', desc: '如 2026-09-11 10:00:00', required: true },
    ] },
  { action: 'wait', name: '等待', desc: '等待元素可见或固定时长', origin: 'native',
    params: [
      { name: 'value', desc: '等待毫秒数，默认 1000' },
      { name: 'element', desc: '可选；定位元素时改为「等元素可见」' },
    ] },
  { action: 'upload', name: '上传', desc: '向文件输入框上传文件', origin: 'native',
    params: [
      { name: 'element', desc: '目标文件输入框（input[type=file]）', required: true },
      { name: 'files / value', desc: '文件中心 ID 或服务器绝对路径（可多个），支持 ${变量}', required: true },
    ] },
  { action: 'screenshot', name: '截图', desc: '捕获当前页面截图（配合节点「执行后截图」策略使用）', origin: 'native' },
  { action: 'evaluate', name: '执行JS', desc: '在页面中执行 JS 表达式（高级用法/逃生门）', origin: 'native',
    params: [
      { name: 'value', desc: 'JS 表达式（返回值进 facts 供提取/断言），支持 ${变量} 注入', required: true },
    ] },
  { action: 'custom', name: '自定义动作', desc: '执行自定义动作库的 JS 模板（动作库页维护），入参 args，返回值进 facts.result', origin: 'wrapped',
    params: [
      { name: 'custom_id', desc: '自定义动作库条目（下拉选择）', required: true },
      { name: 'value', desc: '传给脚本的 args（支持 ${变量}），脚本内以 args 访问' },
    ] },
  // ---- 组合动作（原框架封装 + 全链实测坑位模式，单节点零 JS 完成）----
  { action: 'search', name: '列表检索', desc: '筛选区检索（对齐原框架）：展开/重置筛选区→按字段名填关键字→点查询→等待业务行出现（自动断言）', origin: 'wrapped',
    params: [
      { name: 'value', desc: '检索关键字，支持 ${变量}', required: true },
      { name: 'field', desc: '筛选项字段名（默认 提单号；缺失时自动经「更多筛选」添加）' },
      { name: 'element', desc: '可选；指定检索框元素时走激活式检索框旧路径' },
    ] },
  { action: 'click_text', name: '按文本点击', desc: '按按钮文本点击（空白归一化，兼容「保 存」；匹配按钮/链接/span 任意形态；包含匹配覆盖原 click_text_contains）', origin: 'wrapped',
    params: [
      { name: 'value', desc: '按钮文本，支持 ${变量}', required: true },
      { name: 'match', desc: 'exact 精确匹配（默认，忽略空格）/ contains 包含匹配（如 导入 → 导入报关费用）' },
      { name: 'index', desc: '同名按钮取第 N 个（0 起），如费用表两个「新增标准费用」取第 2 个填 1' },
      { name: 'optional', desc: 'true 无则跳过：按钮可能不存在（如「作废」仅有生效单证时出现），未找到返回 result=absent 不报错' },
    ] },
  { action: 'row_button', name: '行内按钮', desc: '点表格行内操作按钮（tbody 内文本归一化匹配，适配 vxe 固定列副本区，如 详情/编辑）', origin: 'wrapped',
    params: [
      { name: 'value', desc: '行内按钮名，如 详情 / 编辑（空白归一化，「详 情」可写「详情」）', required: true },
      { name: 'row', desc: '行关键字（可选）：限定点包含该关键字的行内按钮（如 ${bl_no}），多行并存时精确定位' },
    ] },
  { action: 'scroll_bottom', name: '滚动到底', desc: '滚动页面及所有滚动容器到底部（激活懒渲染区域）', origin: 'wrapped' },
  { action: 'confirm', name: '弹窗确认', desc: '自适应点弹窗主按钮（确定/确认/继续提交/提交/生效）；轮询模式覆盖原 confirm_wait、可选模式覆盖原 optional_confirm', origin: 'wrapped',
    params: [
      { name: 'wait', desc: 'true 轮询模式：弹窗延迟数秒出现时持续监视并点击（原 confirm_wait）' },
      { name: 'optional', desc: 'true 可选模式：只点「继续提交」类，无弹窗跳过不报错（原 optional_confirm）' },
    ] },
  { action: 'popper_pick', name: '浮层选项', desc: '点下拉浮层中指定文本的选项（轮询等待浮层渲染）', origin: 'wrapped',
    params: [
      { name: 'value', desc: '浮层中的选项文本（需先用「点击」打开下拉）', required: true },
    ] },
  { action: 'toast_watch', name: '提示断言', desc: '轮询等待页面出现指定提示文案（如 保存成功），超时报错并带现场；反向模式断言窗口内不得出现提示', origin: 'wrapped',
    params: [
      { name: 'value', desc: '期望出现的提示文本；absent 反向模式下可空=任何提示都算命中' },
      { name: 'absent', desc: 'true 反向断言：观察窗（步骤超时时间）内出现匹配提示即失败——「点击后不得弹提示」场景' },
      { name: 'optional', desc: 'true 宽容：超时未出现返回 no-toast 不报错（配 optional 点击的条件场景）' },
    ] },
  { action: 'save', name: '保存并确认', desc: '一体化保存：点保存→确认弹窗自动点→无反馈自动补点→以成功提示收尾（必填校验失败会报出错误列）', origin: 'wrapped',
    params: [
      { name: 'value', desc: '期望成功提示，默认「保存成功」，支持 ${变量}' },
      { name: 'element', desc: '可选；自定义保存按钮（默认按文本「保 存」定位）' },
    ] },
  { action: 'uncheck_all', name: '批量取消勾选', desc: '取消定位到的所有已勾选复选框（如「无供应商」列）', origin: 'wrapped',
    params: [
      { name: 'element', desc: '目标复选框组（命中多个则全部取消勾选）', required: true },
    ] },
]

/** 已合并下线的旧动作名 → 兼容别名（存量用例数据显示用；执行侧后端永久兼容） */
const UI_ACTION_ALIASES: Record<string, string> = {
  js_click: 'JS点击（已并入点击·JS模式）',
  click_text_contains: '按包含文本点击（已并入按文本点击·包含匹配）',
  confirm_wait: '轮询确认（已并入弹窗确认·等待）',
  optional_confirm: '可选弹窗继续（已并入弹窗确认·可选）',
}

/** UI 动作 → 中文名（未知动作回退原文） */
export function uiActionName(action?: string | null): string {
  if (!action) return ''
  if (action === 'steps') return '动作组'
  return UI_ACTIONS.find((a) => a.action === action)?.name || UI_ACTION_ALIASES[action] || action
}

// ===== UI 步骤表单共用常量（NodeConfigDrawer / UiActionForm 复用） =====

/** 自定义定位方式（与后端 _INLINE_STRATEGIES 对齐） */
export const STRATEGY_OPTIONS = [
  { value: 'css', label: 'CSS 选择器（#id / .class）' },
  { value: 'xpath', label: 'XPath' },
  { value: 'text', label: '可见文本' },
  { value: 'role', label: 'ARIA 角色（role + name）' },
  { value: 'placeholder', label: '占位符（placeholder）' },
  { value: 'label', label: '表单标签（label）' },
  { value: 'test_id', label: 'data-testid' },
  { value: 'for', label: 'label 的 for 属性' },
]
/** 需要元素定位的动作；press/wait/search/save 的定位可选（无元素时作用于整页/按文本兜底） */
export const ELEMENT_ACTIONS = ['click', 'fill', 'pick', 'select_option', 'check', 'press', 'wait',
  'upload', 'js_click', 'uncheck_all', 'search', 'save']
export const ELEMENT_REQUIRED_ACTIONS = ['click', 'fill', 'pick', 'select_option', 'check', 'upload',
  'js_click', 'uncheck_all']
/** value 为必填文本的组合动作（按钮文本/选项文本/期望提示/检索关键字） */
export const TEXT_VALUE_ACTIONS = new Set(['search', 'click_text', 'click_text_contains', 'row_button',
  'popper_pick', 'toast_watch'])
/** 组合动作的 value 输入框提示（随动作切换） */
export const TEXT_VALUE_META: Record<string, { label: string; tip: string }> = {
  search: { label: '检索关键字', tip: '如提单号 ${bl_no}；默认检索框为 placeholder「提单号」的输入框，可在上方定位自定义' },
  click_text: { label: '按钮文本（精确，忽略空格）', tip: '如 保存 / 编辑 / 生成子订单（兼容「保 存」带空格写法），支持 ${变量}' },
  click_text_contains: { label: '按钮文本片段', tip: '如 导入 → 匹配「导入报关费用」' },
  row_button: { label: '行内按钮名', tip: '如 详情 / 编辑（适配表格固定列副本区的行内操作按钮）' },
  popper_pick: { label: '浮层选项文本', tip: '下拉浮层中的选项文本，如 报关（需先用「点击」打开下拉）' },
  toast_watch: { label: '期望提示文本', tip: '如 保存成功 / 生成子订单成功；超时未出现则该步骤失败并报出页面提示现场' },
}

/**
 * 步骤数据级校验（不依赖表单局部状态）：动作序列折叠态下保存时的全量兜底。
 * element 需先经表单 collect 收敛（库模式=element_id / 自定义=strategy+value）。
 * @returns 校验错误文案；null 表示通过
 */
export function validateUiStepData(st: { action: string; url?: string; value?: any; values?: any[]; custom_id?: number; absent?: boolean; element?: { element_id?: number; value?: string } }): string | null {
  const a = st.action
  if (a === 'custom' && !st.custom_id) return '请选择自定义动作'
  if (ELEMENT_REQUIRED_ACTIONS.includes(a) && !st.element?.element_id && !st.element?.value) {
    return '请定位元素（元素库引用或自定义定位值）'
  }
  if (a === 'goto' && !st.url?.trim()) return '需要填写页面 URL'
  if (a === 'fill' && (st.value == null || st.value === '')) return '需要填写输入内容'
  if (TEXT_VALUE_ACTIONS.has(a) && !st.value?.toString().trim() && !(a === 'toast_watch' && st.absent)) {
    return `需要填写${TEXT_VALUE_META[a]?.label || '文本值'}`
  }
  if (['pick', 'type'].includes(a) && !st.value?.toString().trim()) return '需要填写值'
  if (a === 'evaluate' && !st.value?.toString().trim()) return '需要填写 JS 表达式'
  if (a === 'select_option' && !(st.values?.length || st.value != null)) return '至少填写一个选项值'
  return null
}

/**
 * 解析侧边菜单激活项：按「段边界」的最长前缀匹配。
 * '/envs/edit/5' → '/envs'；'/executions2' 不匹配 '/executions'；
 * 无任何匹配时回退当前路径（保持 el-menu 原生行为）。
 */
export function resolveMenuActive(path: string, menuPaths: string[]): string {
  let best = ''
  for (const mp of menuPaths) {
    if ((path === mp || path.startsWith(mp + '/')) && mp.length > best.length) {
      best = mp
    }
  }
  return best || path
}

/**
 * 防抖：等待窗口内多次调用只生效最后一次（列表搜索统一范式用）。
 * @param wait 毫秒
 */
export function debounce<T extends (...args: any[]) => void>(fn: T, wait = 300): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn(...args)
    }, wait)
  }
}
