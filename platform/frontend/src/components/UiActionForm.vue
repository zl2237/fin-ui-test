<template>
  <!-- label-width 100px：4 字标签 + 问号图标在 90px 下贴边折行（2026-11-05），配合下方 nowrap 双保险 -->
  <el-form label-width="100px" class="ui-step-form">
    <el-form-item required>
      <template #label>动作类型<HintTip :content="actionDesc" /></template>
      <!-- 统一动作下拉（2026-11-05）：与节点配置「+ 添加动作」共用 ActionSelect，交互一致 -->
      <ActionSelect :model-value="actionSelectValue" style="width: 100%" :custom-actions="customActions" :action-docs="actionDocs" @update:model-value="onActionChange" />
    </el-form-item>
    <template v-if="st.action === 'goto'">
      <el-form-item label="页面 URL" required>
        <div class="ds-menu-row">
          <el-input v-model="st.url" placeholder="https://… 或 /相对路径（自动拼环境 base_url），支持 ${变量}" @focus="urlIns.onSqlFocus" />
          <DatasetVarMenu v-bind="dvmProps" @insert="urlIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
        </div>
      </el-form-item>
      <el-form-item label="加载条件">
        <el-select v-model="st.wait_for" style="width: 100%">
          <el-option label="load（默认，load 事件）" value="load" />
          <el-option label="domcontentloaded（DOM 解析完成）" value="domcontentloaded" />
          <el-option label="networkidle（网络空闲，最慢）" value="networkidle" />
        </el-select>
      </el-form-item>
    </template>
    <!-- 元素定位：元素库引用（优先）或自定义单策略；press/wait 可不定位（作用于整页） -->
    <template v-if="needsElement">
      <el-form-item label="定位来源">
        <el-radio-group v-model="elementMode">
          <el-radio-button value="library">从元素库选择</el-radio-button>
          <el-radio-button value="custom">自定义</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <template v-if="elementMode === 'library'">
        <!-- 节点页面域：新编排模型下由节点固定（nodeScope），仅存量无域节点可改 -->
        <el-form-item v-if="!props.nodeScope" label="页面域" :required="elementRequired">
          <el-select v-model="elementScope" filterable clearable placeholder="选择页面域" style="width: 100%" @change="onScopeChange">
            <el-option v-for="s in scopeList" :key="s" :label="scopeDisplay(s)" :value="s">
              <div class="scope-opt">
                <span>{{ props.scopeLabels?.[s] || s }}</span>
                <span v-if="props.scopeLabels?.[s]" class="scope-en">{{ s }}</span>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="选择元素" :required="elementRequired">
          <el-select v-model="st.element!.element_id" filterable clearable :placeholder="props.nodeScope ? `仅限本节点页面域「${scopeDisplay(props.nodeScope)}」下的元素` : '先选页面域，再选元素'" style="width: 100%" :disabled="!elementScope">
            <el-option v-for="el in scopeElements" :key="el.id" :label="el.element_key" :value="el.id">
              <!-- 仅显示 key（描述过宽曾致下拉无限膨胀）；hover title 按需查看描述 -->
              <span class="element-opt" :title="el.description ? `${el.element_key}（${el.description}）` : el.element_key">{{ el.element_key }}</span>
            </el-option>
          </el-select>
          <!-- 跨域/悬空是数据态错误，必须直接陈列（不收浮层） -->
          <p v-if="crossScopeElement" class="tip action-tip dangling-tip">
            当前引用的元素「{{ crossScopeElement }}」不属于节点页面域 {{ scopeDisplay(props.nodeScope!) }}，请重选本域元素
          </p>
          <p v-else-if="danglingElement" class="tip action-tip dangling-tip">
            当前引用的元素 #{{ st.element!.element_id }} 不在元素库中（元素库变更后遗留的悬空引用），请重选页面域与元素
          </p>
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label="定位方式" :required="elementRequired">
          <el-select v-model="st.element!.strategy" style="width: 100%">
            <el-option v-for="s in STRATEGY_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="定位值" :required="elementRequired">
          <el-input v-model="st.element!.value" :placeholder="strategyHint?.example || '先选定位方式'" />
        </el-form-item>
        <el-form-item v-if="st.element!.strategy === 'role'" label="角色名称">
          <el-input v-model="st.element!.name" placeholder="如 提交 / Submit（get_by_role 的 name）" />
        </el-form-item>
      </template>
    </template>
    <!-- value/values：随动作类型切换形态（${} 取值控件旁带数据集引用插入器） -->
    <el-form-item v-if="st.action === 'fill'" label="输入内容" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value" placeholder="填入文本，支持 ${变量}" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="TEXT_VALUE_ACTIONS.has(st.action)" label="文本值" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value" :placeholder="textValuePlaceholder" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'save'" label="期望提示">
      <div class="ds-menu-row">
        <el-input v-model="st.value" placeholder="默认「保存成功」；留空按文本「保 存」定位保存按钮，支持 ${变量}" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="['pick', 'type', 'date'].includes(st.action)" label="值" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value"
                  :placeholder="st.action === 'pick' ? '选项文本，如 海运费，支持 ${变量}' : (st.action === 'date' ? '如 2026-09-11 10:00:00' : '逐字输入的内容，支持 ${变量}')"
                  @focus="valIns.onSqlFocus" />
        <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'press'" label="按键" required>
      <!-- 可选可输：常见键下拉杜绝大小写手误（键名严格区分，写错执行期当场报错）；
           组合键开放集合（Control+Shift+Home 等）必须保留自由输入 -->
      <el-select v-model="st.value" filterable allow-create default-first-option clearable
                 placeholder="Enter（默认）；组合键如 Control+A 可直接输入" style="width: 100%">
        <el-option v-for="k in PRESS_KEYS" :key="k" :label="k" :value="k" />
      </el-select>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'wait'">
      <template #label>等待时长<HintTip v-if="needsElement" content="定位了元素时改为「等元素可见」，时长仅作记录" /></template>
      <el-input-number v-model="waitValue" :min="0" :step="500" controls-position="right" style="width: 180px" />
      <span class="wait-unit">ms</span>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'evaluate'" label="JS 表达式" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value" type="textarea" :rows="3" placeholder="如 document.title；支持 ${变量} 注入" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'select_option'" label="选项值" required>
      <el-select v-model="optionValues" multiple filterable allow-create default-first-option placeholder="输入选项值后回车，可多个" style="width: 100%" />
    </el-form-item>
    <!-- custom：自定义动作模板引用 + 传参 -->
    <template v-else-if="st.action === 'custom'">
      <el-form-item label="动作模板" required>
        <el-select v-model="st.custom_id" filterable clearable placeholder="选择自定义动作（动作库页维护）" style="width: 100%">
          <el-option v-for="ca in customActions" :key="ca.id" :value="ca.id"
                     :label="ca.description ? `${ca.name}（${ca.description}）` : ca.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="传参 args">
        <div class="ds-menu-row">
          <el-input v-model="st.value" placeholder="传给脚本的参数（脚本内以 args 访问），支持 ${变量}" @focus="valIns.onSqlFocus" />
          <DatasetVarMenu v-bind="dvmProps" @insert="valIns.onSqlInsert" @rows-changed="emit('rows-changed')" />
        </div>
      </el-form-item>
    </template>
    <!-- 合并参数：click_text 匹配方式 / click 模式 / confirm 形态 -->
    <el-form-item v-if="st.action === 'click_text'" label="同名序号">
      <el-input-number v-model="clickIndex" :min="0" :step="1" controls-position="right" placeholder="第 N 个（0 起）" style="width: 120px" />
    </el-form-item>
    <el-form-item v-if="st.action === 'click_text'" label="匹配方式">
      <el-radio-group v-model="clickMatch">
        <el-radio-button value="exact">精确（默认）</el-radio-button>
        <el-radio-button value="contains">包含</el-radio-button>
      </el-radio-group>
    </el-form-item>
    <el-form-item v-if="st.action === 'click_text'" label="无则跳过">
      <el-switch v-model="clickOptional" />
    </el-form-item>
    <!-- toast_watch：反向断言（不得出现）/ 宽容（超时不报错），二者互斥 -->
    <template v-if="st.action === 'toast_watch'">
      <el-form-item label="反向断言">
        <el-switch v-model="toastAbsent" />
      </el-form-item>
      <el-form-item label="无则跳过">
        <el-switch v-model="toastOptional" />
      </el-form-item>
    </template>
    <el-form-item v-if="st.action === 'click'">
      <template #label>点击模式<HintTip :content="clickMode === 'js'
        ? '合成 click 事件，元素在 DOM 即可点（不可见/被遮挡时用，原 js_click）'
        : '真实鼠标事件；被遮挡/动画未稳被拦时开下方「强制点击」跳过前置校验'" /></template>
      <el-radio-group v-model="clickMode">
        <el-radio-button value="default">普通</el-radio-button>
        <el-radio-button value="js">JS 直调</el-radio-button>
      </el-radio-group>
    </el-form-item>
    <template v-if="st.action === 'confirm'">
      <el-form-item label="轮询等待">
        <el-switch v-model="confirmWait" />
      </el-form-item>
      <el-form-item label="无则跳过">
        <el-switch v-model="confirmOptional" />
      </el-form-item>
    </template>
    <!-- 超时时间仅对引擎消费 timeout_ms 的动作显示（NO_TIMEOUT_ACTIONS 逐 handler 核验；
         toast_watch 的超时即观察窗，保留） -->
    <el-form-item v-if="!NO_TIMEOUT_ACTIONS.has(st.action)" label="超时时间">
      <el-input-number v-model="timeoutMs" :min="0" :step="1000" controls-position="right" style="width: 180px" />
      <span class="wait-unit">ms</span>
    </el-form-item>
    <!-- 强制点击仅普通模式有效（js 模式引擎不读 force，隐藏避免误导） -->
    <el-form-item v-if="st.action === 'click' && clickMode !== 'js'" label="强制点击">
      <el-switch v-model="st.force" />
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
/**
 * UI 动作步骤表单：页面级节点（动作组）中单个步骤的参数编辑。
 * 直接 mutate props.step（父组件持有草稿），collect() 时做参数收敛与校验。
 * 元素库数据由父组件加载一次传入（组内各步骤共享，避免重复请求）。
 */
import { ref, computed, watch } from 'vue'
import type { UiElement, UiStep, CustomAction, UiActionDoc } from '@/api'
import { UI_ACTIONS, STRATEGY_OPTIONS, STRATEGY_HINTS, validateLocatorValue, ELEMENT_ACTIONS, ELEMENT_REQUIRED_ACTIONS, TEXT_VALUE_ACTIONS, TEXT_VALUE_META, NO_TIMEOUT_ACTIONS } from '@/utils/ui'
import ActionSelect from './ActionSelect.vue'
import HintTip from './HintTip.vue'
import DatasetVarMenu, { type DsVarSheet } from './DatasetVarMenu.vue'
import { useSqlInsert } from '@/composables/useSqlInsert'

const props = defineProps<{
  step: UiStep
  uiElements: UiElement[]
  customActions: CustomAction[]
  /** 动作描述覆盖（动作库管理 → 编辑描述）；wrapped 动作优先显示项目覆盖文本 */
  actionDocs?: UiActionDoc[]
  /** 绑定数据集的 sheet 清单（${sheet.字段} 插入器数据源；空=不渲染插入按钮） */
  dsSheets?: DsVarSheet[]
  /** 归属用例 + 绑定数据集 id（插入器「临时新增一行」落点，透传 DatasetVarMenu） */
  caseId?: number
  boundDatasetId?: number | null
  /** 页面域 scope → 中文名（元素库页维护）：下拉/回显显示中文而非裸编码 */
  scopeLabels?: Record<string, string>
  /** 节点页面域（编排改造：节点=页面域）：固定元素可选范围，不传则步骤内自选域 */
  nodeScope?: string
}>()
const emit = defineEmits<{ (e: 'rows-changed'): void }>()

/** DatasetVarMenu 公共绑定（7 处插入器同一数据源/落点，仅 insert 通道不同） */
const dvmProps = computed(() => ({
  sheets: props.dsSheets,
  caseId: props.caseId,
  boundDatasetId: props.boundDatasetId,
}))

// 光标处插入 ${sheet.字段}：value 与 url 各一条通道（复用 SQL 引用插入器，
// 记录最后聚焦控件，插入后回焦定位到插入串之后）
const valIns = useSqlInsert(
  (v) => { st.value.value = v },
  () => st.value.value ?? '',
)
const urlIns = useSqlInsert(
  (v) => { st.value.url = v },
  () => st.value.url ?? '',
)

const st = computed(() => props.step)
/** 悬空元素引用：element_id 不在元素库（库重建/元素删除后遗留）——
 * 页面域回显空、下拉显示原始数字即此态；显式提示重选而非静默 */
const danglingElement = computed(() => {
  const id = st.value.element?.element_id
  return id != null && !props.uiElements.some((x) => x.id === id)
})
const selectedCustom = computed(() => props.customActions.find((c) => c.id === st.value.custom_id))
const needsElement = computed(() => ELEMENT_ACTIONS.includes(st.value.action))
const elementRequired = computed(() => ELEMENT_REQUIRED_ACTIONS.includes(st.value.action))
const actionDesc = computed(() => {
  const a = UI_ACTIONS.find((x) => x.action === st.value.action)
  if (!a) return ''
  const overridden = props.actionDocs?.find((d) => d.action_key === a.action)?.usage_text
  return overridden || a.desc
})
const textValuePlaceholder = computed(() => TEXT_VALUE_META[st.value.action]?.label || '文本值，支持 ${变量}')

// 元素定位模式：元素库引用（element_id）/ 自定义单策略（strategy+value）
const elementMode = ref<'library' | 'custom'>('library')
const elementScope = ref<string>('')
const scopeList = computed(() => [...new Set(props.uiElements.map((e) => e.page_scope))].sort())
// 节点页面域固定时元素仅限本域（编排改造：动作不得跨域）
const effectiveScope = computed(() => props.nodeScope || elementScope.value)
const scopeElements = computed(() => props.uiElements.filter((e) => e.page_scope === effectiveScope.value))
/** 库元素跨域引用（nodeScope 固定后遗留）：显式提示重选 */
const crossScopeElement = computed(() => {
  if (!props.nodeScope) return ''
  const id = st.value.element?.element_id
  if (id == null) return ''
  const found = props.uiElements.find((x) => x.id === id)
  if (!found || found.page_scope === props.nodeScope) return ''
  return found.description || found.element_key
})

/** press 常用键名（Playwright 规范写法；组合键走 allow-create 自由输入） */
const PRESS_KEYS = [
  'Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'Space',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
  'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
  'Control+A', 'Control+C', 'Control+V', 'Control+X', 'Control+Enter', 'Shift+Tab',
]

/** select_option 的多值输入 / wait 的时长 / click_text 序号与匹配 / click 模式 / confirm 形态（与 step 字段互转） */
const optionValues = ref<string[]>([])
const waitValue = ref<number>(1000)
const clickIndex = ref<number>(0)
const clickMatch = ref<'exact' | 'contains'>('exact')
const clickOptional = ref(false)
const toastAbsent = ref(false)
const toastOptional = ref(false)
const clickMode = ref<'default' | 'js'>('default')
/** 定位值随策略键实时换示例与语义提示（role 的可访问名走专属「角色名称」字段，提示单独说） */
const strategyHint = computed(() => {
  const h = STRATEGY_HINTS[st.value.element?.strategy ?? '']
  if (!h) return null
  return st.value.element?.strategy === 'role'
    ? { ...h, tip: 'ARIA 角色名（button/link/tab…），可访问名填下方「角色名称」' }
    : h
})
const confirmWait = ref(false)
const confirmOptional = ref(false)
const timeoutMs = computed<number>({
  get: () => st.value.timeout_ms ?? 15000,
  set: (v: number) => { st.value.timeout_ms = v },
})

/** 页面域下拉显示值：有中文名时「中文（编码）」，否则裸编码 */
function scopeDisplay(s: string): string {
  const zh = props.scopeLabels?.[s]
  return zh ? `${zh}（${s}）` : s
}

/** 切换动作：保留通用参数（value/timeout 等），清掉与新动作无关的专属字段 */
function onActionChange(action: string) {
  // 项目自定义模板直选项：一步落到 custom 动作 + 绑定 custom_id
  if (action.startsWith('@custom/')) {
    const id = Number(action.slice('@custom/'.length))
    st.value.action = 'custom'
    st.value.custom_id = id
    return
  }
  if (action === 'custom') st.value.custom_id = undefined  // 回到通用入口时清绑定，下方模板下拉重选
  st.value.action = action as UiStep['action']
}

/** 下拉显示值：绑定了模板的 custom 步骤显示对应模板项（与选项 value 对齐） */
const actionSelectValue = computed(() => {
  const s = st.value
  if (s.action === 'custom' && s.custom_id && props.customActions.some((c) => c.id === s.custom_id)) {
    return `@custom/${s.custom_id}`
  }
  return s.action
})

/** 步骤对象变化（加载/删除致复用）时同步局部编辑状态 */
watch(
  () => props.step,
  (s) => {
    if (!s.element) s.element = {}
    elementMode.value = s.element.element_id ? 'library' : (s.element.strategy ? 'custom' : 'library')
    optionValues.value = (s.values ?? (s.value != null && s.action === 'select_option' ? [String(s.value)] : [])).map(String)
    waitValue.value = s.action === 'wait' ? Number(s.value ?? 1000) || 1000 : 1000
    clickIndex.value = Number(s.index ?? 0) || 0
    clickMatch.value = s.match === 'contains' ? 'contains' : 'exact'
    clickOptional.value = !!s.optional
    toastAbsent.value = !!s.absent
    toastOptional.value = !!s.optional
    clickMode.value = s.mode === 'js' ? 'js' : 'default'
    confirmWait.value = !!s.wait
    confirmOptional.value = !!s.optional
    // 元素库引用回显：定位到所属页面域（节点域固定时锚定节点域）
    if (props.nodeScope) {
      elementScope.value = props.nodeScope
    } else if (s.element.element_id) {
      const found = props.uiElements.find((x) => x.id === s.element!.element_id)
      if (found) elementScope.value = found.page_scope
    } else {
      elementScope.value = ''
    }
  },
  { immediate: true },
)

/** 切换页面域：清掉已选元素（跨域 element_id 无效） */
function onScopeChange() {
  st.value.element!.element_id = undefined
}

/**
 * 收敛本步骤参数并校验：把局部编辑状态写回 step、清理与动作无关的脏字段。
 * @returns 校验错误文案；null 表示通过
 */
function collect(): string | null {
  const p = st.value
  // 未选元素的动作清掉 element，避免残留脏配置进入执行参数
  if (!needsElement.value) {
    p.element = undefined
  } else if (elementMode.value === 'library') {
    if (elementRequired.value && !p.element?.element_id) {
      return '请从元素库选择元素（或切到「自定义」手动定位）'
    }
    // 跨域拦截（与后端 validate_ui_scope_bindings 同语义）：固定域节点不得引用他域元素
    if (props.nodeScope && p.element?.element_id) {
      const found = props.uiElements.find((x) => x.id === p.element!.element_id)
      if (found && found.page_scope !== props.nodeScope) {
        return `元素「${found.description || found.element_key}」不属于本节点页面域，请重选本域元素`
      }
    }
    p.element = p.element?.element_id ? { element_id: p.element.element_id } : undefined
  } else {
    if (elementRequired.value && !p.element?.value) {
      return '请填写元素定位值'
    }
    // 格式校验：CSS 框里贴 XPath 这类张冠李戴在编排期拦下（执行期只会表现为定位超时）
    const fmtErr = validateLocatorValue(p.element?.strategy || '', p.element?.value || '')
    if (fmtErr) return fmtErr
    const { strategy, value, name } = p.element ?? ({} as NonNullable<UiStep['element']>)
    p.element = strategy ? { strategy, value, name } : undefined
  }
  if (p.action === 'goto' && !p.url?.trim()) return '导航动作需要填写页面 URL'
  if (p.action === 'fill' && (p.value == null || p.value === '')) return '输入动作需要填写输入内容'
  if (TEXT_VALUE_ACTIONS.has(p.action) && !p.value?.toString().trim()
      && !(p.action === 'toast_watch' && p.absent)) {
    return `该动作需要填写${TEXT_VALUE_META[p.action]?.label || '文本值'}`
  }
  if (['pick', 'type'].includes(p.action) && !p.value?.toString().trim()) return '该动作需要填写值'
  if (p.action === 'evaluate' && !p.value?.toString().trim()) return '执行JS动作需要填写 JS 表达式'
  if (p.action === 'select_option') {
    if (!optionValues.value.length) return '下拉选择动作至少填写一个选项值'
    p.values = [...optionValues.value]
    p.value = undefined
  } else {
    p.values = undefined
  }
  if (p.action === 'wait') p.value = waitValue.value
  // press 键名首尾空格修剪（键名中空格无意义，尾随空格是 "Unknown key" 陷阱）
  if (p.action === 'press' && typeof p.value === 'string') p.value = p.value.trim()
  if (p.action === 'click_text') {
    p.index = clickIndex.value || undefined
    p.match = clickMatch.value === 'contains' ? 'contains' : undefined
    p.optional = clickOptional.value ? true : undefined
  } else {
    p.index = undefined
    p.match = undefined
  }
  // toast_watch：absent 反向 / optional 宽容（互斥，前者优先）；文本在 absent 模式可空
  if (p.action === 'toast_watch') {
    if (toastAbsent.value) {
      p.absent = true
      p.optional = undefined
    } else {
      p.absent = undefined
      p.optional = toastOptional.value ? true : undefined
    }
  } else {
    p.absent = undefined
    p.optional = (p.action === 'click_text' && clickOptional.value) ? true : undefined
  }
  p.mode = (p.action === 'click' && clickMode.value === 'js') ? 'js' : undefined
  p.wait = (p.action === 'confirm' && confirmWait.value) ? true : undefined
  p.optional = (p.action === 'confirm' && confirmOptional.value) ? true : undefined
  if (p.action !== 'goto') p.wait_for = undefined
  // js 模式引擎不消费 force（_do_click 提前 return），不留死配置
  if (p.action !== 'click' || clickMode.value === 'js') p.force = undefined
  if (p.action !== 'custom') p.custom_id = undefined
  return null
}

defineExpose({ collect })
</script>

<style scoped>
/* label 单行强制：含问号图标的 4 字标签（动作类型/点击模式/等待时长）不许折行 */
:deep(.el-form-item__label) {
  white-space: nowrap;
}
.ui-step-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
/* ${} 取值控件 + 数据集插入按钮同行：输入框撑满，按钮贴右侧不换行 */
.ds-menu-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  width: 100%;
}
.ds-menu-row .el-input {
  flex: 1;
  min-width: 0;
}
.ds-menu-row > :deep(.dvm-link) {
  flex-shrink: 0;
  line-height: 22px;
  padding-top: 4px;
}
/* 页面域下拉项：中文名主显 + scope 编码次显（与元素库页一致） */
.scope-opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.scope-opt .scope-en {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-faint);
}
/* 元素下拉项：仅 key（mono 单行，溢出省略），描述走 hover title */
.element-opt {
  display: block;
  font-family: var(--app-font-mono);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tip {
  margin-top: 4px;
  margin-bottom: 0;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
  width: 100%;
}
.tip code {
  background: var(--app-hover);
  padding: 1px 5px;
  border-radius: 3px;
}
.dangling-tip {
  color: var(--el-color-danger);
}
.inline-tip {
  margin: 0 0 0 10px;
  width: auto;
}
.wait-unit {
  margin-left: 8px;
  color: var(--app-text-muted);
}
</style>
