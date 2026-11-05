import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { resolveMenuActive, debounce, UI_ACTIONS, SELECTABLE_UI_ACTIONS, uiActionName, validateUiStepData, ELEMENT_ACTIONS, ELEMENT_REQUIRED_ACTIONS, NO_TIMEOUT_ACTIONS, STRATEGY_OPTIONS, STRATEGY_HINTS, validateLocatorValue } from '../ui'

describe('resolveMenuActive', () => {
  const menuPaths = ['/home', '/apis', '/cases', '/executions', '/envs']

  it('完全匹配', () => {
    expect(resolveMenuActive('/apis', menuPaths)).toBe('/apis')
  })

  it('前缀匹配（段边界）', () => {
    expect(resolveMenuActive('/envs/edit/5', menuPaths)).toBe('/envs')
  })

  it('段边界不误匹配（/executions2 不匹配 /executions）', () => {
    expect(resolveMenuActive('/executions2', menuPaths)).toBe('/executions2')
  })

  it('无匹配回退当前路径', () => {
    expect(resolveMenuActive('/unknown', menuPaths)).toBe('/unknown')
  })

  it('最长前缀优先', () => {
    expect(resolveMenuActive('/apis/group/1', ['/api', '/apis', '/apis/group'])).toBe('/apis/group')
  })
})

describe('UI 动作词表（retired 精简，2026-11-05）', () => {
  it('SELECTABLE 不含已下线的 screenshot / select_option；词条本身仍留在 UI_ACTIONS（存量回显）', () => {
    const selectableKeys = SELECTABLE_UI_ACTIONS.map((a) => a.action)
    expect(selectableKeys).not.toContain('screenshot')
    expect(selectableKeys).not.toContain('select_option')
    expect(UI_ACTIONS.map((a) => a.action)).toContain('screenshot')
    expect(UI_ACTIONS.map((a) => a.action)).toContain('select_option')
    expect(UI_ACTIONS.filter((a) => a.retired).map((a) => a.action)).toEqual(['select_option', 'screenshot'])
  })

  it('uiActionName 对已下线动作与别名兜底链仍生效', () => {
    expect(uiActionName('screenshot')).toBe('截图')
    expect(uiActionName('select_option')).toBe('下拉选择(原生)')
    expect(uiActionName('js_click')).toContain('已并入')
    expect(uiActionName('__unknown__')).toBe('__unknown__')
  })

  it('validateUiStepData 对存量 select_option 步骤校验仍兼容', () => {
    expect(validateUiStepData({ action: 'select_option', element: { element_id: 1 } })).toBe('至少填写一个选项值')
    expect(validateUiStepData({ action: 'select_option', element: { element_id: 1 }, value: 'o1' })).toBeNull()
  })
})

describe('动作-配置项匹配（2026-11-05 逐 handler 核验）', () => {
  it('type/date 引擎经 _locator 定位，必须出现在元素必填清单', () => {
    expect(ELEMENT_ACTIONS).toContain('type')
    expect(ELEMENT_ACTIONS).toContain('date')
    expect(ELEMENT_REQUIRED_ACTIONS).toContain('type')
    expect(ELEMENT_REQUIRED_ACTIONS).toContain('date')
    expect(validateUiStepData({ action: 'type', value: 'x' })).toBe('请定位元素（元素库引用或自定义定位值）')
    expect(validateUiStepData({ action: 'date', value: '2026-01-01' })).toBe('请定位元素（元素库引用或自定义定位值）')
  })

  it('不消费 timeout_ms 的动作在隐藏名单（超时字段无效）', () => {
    for (const a of ['evaluate', 'custom', 'row_button', 'scroll_bottom', 'confirm', 'popper_pick']) {
      expect(NO_TIMEOUT_ACTIONS.has(a)).toBe(true)
    }
    // 消费 timeout 的代表动作不在名单
    for (const a of ['goto', 'click', 'wait', 'toast_watch', 'type', 'date']) {
      expect(NO_TIMEOUT_ACTIONS.has(a)).toBe(false)
    }
  })
})

describe('定位策略提示（STRATEGY_HINTS，2026-11-05）', () => {
  it('覆盖引擎 _STRATEGY_PRIORITY 全部 13 键（含 role），示例与提示齐备', () => {
    const chain = ['test_id', 'for', 'label', 'placeholder', 'button', 'tab', 'role', 'text',
      'checkbox', 'toast', 'css', 'xpath', 'full_xpath']
    expect(Object.keys(STRATEGY_HINTS)).toHaveLength(chain.length)
    for (const k of chain) {
      expect(STRATEGY_HINTS[k]?.example, k).toBeTruthy()
      expect(STRATEGY_HINTS[k]?.tip, k).toBeTruthy()
    }
  })

  it('表单可选的定位方式（STRATEGY_OPTIONS）都有对应提示', () => {
    for (const s of STRATEGY_OPTIONS) {
      expect(STRATEGY_HINTS[s.value], s.value).toBeTruthy()
    }
  })
})

describe('定位值格式校验（validateLocatorValue，2026-11-05）', () => {
  it('CSS 框里贴 XPath 当场拦下', () => {
    expect(validateLocatorValue('css', '//button[@id="save"]')).toContain('XPath')
    expect(validateLocatorValue('css', '/html/body/div')).toContain('XPath')
  })
  it('XPath 缺 // 开头 / 带 xpath= 前缀拦下', () => {
    expect(validateLocatorValue('xpath', 'button[@id="save"]')).toContain('//')
    expect(validateLocatorValue('xpath', 'xpath=//button')).toContain('前缀')
    expect(validateLocatorValue('full_xpath', 'html/body')).toContain('//')
  })
  it('id 类键带 # 或空格拦下（用户贴了整段 selector）', () => {
    expect(validateLocatorValue('test_id', '#submit-btn')).toContain('#')
    expect(validateLocatorValue('for', 'cust name')).toContain('空格')
    expect(validateLocatorValue('tab', 'tab-a tab-b')).toBeTruthy()
  })
  it('合法值与语义键不做格式约束', () => {
    expect(validateLocatorValue('css', '.el-dialog .el-button--primary')).toBeNull()
    expect(validateLocatorValue('xpath', "//button[contains(text(),'查询')]")).toBeNull()
    expect(validateLocatorValue('xpath', '(//div)[2]')).toBeNull()
    expect(validateLocatorValue('test_id', 'submit-btn')).toBeNull()
    expect(validateLocatorValue('label', '提单 号')).toBeNull()
    expect(validateLocatorValue('text', '')).toBeNull()
  })
  it('validateUiStepData 数据级兜底：折叠步骤的坏格式也拦（原仅表单 collect 校验，返回值被丢弃而静默失效）', () => {
    expect(validateUiStepData({ action: 'click', element: { strategy: 'css', value: '/html/body/div' } })).toContain('XPath')
    expect(validateUiStepData({ action: 'click', element: { strategy: 'xpath', value: 'button[@id="save"]' } })).toContain('//')
    expect(validateUiStepData({ action: 'click', element: { strategy: 'test_id', value: '#submit-btn' } })).toBeTruthy()
    // 合法自定义定位与元素库引用不受影响
    expect(validateUiStepData({ action: 'click', element: { strategy: 'css', value: '.btn-save' } })).toBeNull()
    expect(validateUiStepData({ action: 'click', element: { element_id: 7 } })).toBeNull()
  })
})

describe('debounce', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('多次调用只生效最后一次', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)
    debounced('a')
    debounced('b')
    debounced('c')
    expect(fn).not.toHaveBeenCalled()
    vi.advanceTimersByTime(300)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith('c')
  })

  it('间隔超过 wait 的调用各生效一次', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 100)
    debounced('first')
    vi.advanceTimersByTime(100)
    debounced('second')
    vi.advanceTimersByTime(100)
    expect(fn).toHaveBeenCalledTimes(2)
    expect(fn).toHaveBeenNthCalledWith(1, 'first')
    expect(fn).toHaveBeenNthCalledWith(2, 'second')
  })

  it('默认 wait=300', () => {
    const fn = vi.fn()
    const debounced = debounce(fn)
    debounced()
    vi.advanceTimersByTime(299)
    expect(fn).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
