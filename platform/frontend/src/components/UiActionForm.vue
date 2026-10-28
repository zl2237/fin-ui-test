<template>
  <el-form label-width="90px" class="ui-step-form">
    <el-form-item label="动作类型" required>
      <el-select :model-value="actionSelectValue" style="width: 100%" @update:model-value="onActionChange">
        <el-option v-for="a in UI_ACTIONS" :key="a.action" :label="`${a.name}（${a.action}）`" :value="a.action">
          <div class="action-opt">
            <span class="action-opt-name">{{ a.name }}</span>
            <span class="action-opt-code">{{ a.action }}</span>
            <span class="action-opt-tag" :class="`origin-${a.origin}`">{{ UI_ACTION_ORIGINS[a.origin].label }}</span>
          </div>
        </el-option>
        <!-- 项目自定义动作（JS 模板）直列下拉：一步选中，免去先选 custom 再选模板 -->
        <el-option-group v-if="customActions.length" label="项目自定义（动作库维护）">
          <el-option
            v-for="ca in customActions" :key="`@custom/${ca.id}`" :value="`@custom/${ca.id}`"
            :label="ca.description ? `${ca.name}（${firstLine(ca.description)}）` : ca.name"
          >
            <div class="action-opt">
              <span class="action-opt-name">{{ ca.name }}</span>
              <span class="action-opt-code">custom:{{ ca.id }}</span>
              <span class="action-opt-tag origin-wrapped">自定义</span>
            </div>
          </el-option>
        </el-option-group>
      </el-select>
      <p class="tip action-tip">{{ actionDesc }}</p>
    </el-form-item>
    <template v-if="st.action === 'goto'">
      <el-form-item label="页面 URL" required>
        <div class="ds-menu-row">
          <el-input v-model="st.url" placeholder="https://… 或 /相对路径（自动拼环境 base_url），支持 ${变量}" @focus="urlIns.onSqlFocus" />
          <DatasetVarMenu :sheets="dsSheets" @insert="urlIns.onSqlInsert" />
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
            <el-option v-for="el in scopeElements" :key="el.id" :label="elementLabel(el)" :value="el.id" />
          </el-select>
          <p v-if="crossScopeElement" class="tip action-tip dangling-tip">
            当前引用的元素「{{ crossScopeElement }}」不属于节点页面域 {{ scopeDisplay(props.nodeScope!) }}，请重选本域元素
          </p>
          <p v-else-if="danglingElement" class="tip action-tip dangling-tip">
            当前引用的元素 #{{ st.element!.element_id }} 不在元素库中（元素库变更后遗留的悬空引用），请重选页面域与元素
          </p>
          <p v-else class="tip action-tip">{{ props.nodeScope ? `只能选择本页面域（${scopeDisplay(props.nodeScope)}）下的元素；跨域元素请另建节点` : '元素库在「元素库」页面维护（支持 locator JSON 批量导入）' }}</p>
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label="定位方式" :required="elementRequired">
          <el-select v-model="st.element!.strategy" style="width: 100%">
            <el-option v-for="s in STRATEGY_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="定位值" :required="elementRequired">
          <el-input v-model="st.element!.value" placeholder="如 #submit-btn / //button[@id='save']" />
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
        <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="TEXT_VALUE_ACTIONS.has(st.action)" label="文本值" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value" :placeholder="textValuePlaceholder" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
      </div>
      <p class="tip action-tip">{{ textValueTip }}</p>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'save'" label="期望提示">
      <div class="ds-menu-row">
        <el-input v-model="st.value" placeholder="默认「保存成功」；也可填其他成功提示文本，支持 ${变量}" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
      </div>
      <p class="tip action-tip">留空时按文本「保 存」定位保存按钮，成功以该提示出现为准</p>
    </el-form-item>
    <el-form-item v-else-if="['pick', 'type', 'date'].includes(st.action)" label="值" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value"
                  :placeholder="st.action === 'pick' ? '选项文本，如 海运费，支持 ${变量}' : (st.action === 'date' ? '如 2026-09-11 10:00:00' : '逐字输入的内容，支持 ${变量}')"
                  @focus="valIns.onSqlFocus" />
        <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'press'" label="按键" required>
      <el-input v-model="st.value" placeholder="如 Enter / Control+A（默认 Enter）" />
    </el-form-item>
    <el-form-item v-else-if="st.action === 'wait'" label="等待时长">
      <el-input-number v-model="waitValue" :min="0" :step="500" controls-position="right" style="width: 180px" />
      <span class="wait-unit">ms</span>
      <span v-if="needsElement" class="tip inline-tip">定位了元素时改为「等元素可见」，时长仅作记录</span>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'evaluate'" label="JS 表达式" required>
      <div class="ds-menu-row">
        <el-input v-model="st.value" type="textarea" :rows="3" placeholder="如 document.title；支持 ${变量} 注入" @focus="valIns.onSqlFocus" />
        <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
      </div>
    </el-form-item>
    <el-form-item v-else-if="st.action === 'select_option'" label="选项值" required>
      <el-select v-model="optionValues" multiple filterable allow-create default-first-option placeholder="输入选项值后回车，可多个" style="width: 100%" />
      <p class="tip action-tip">对应 select 的 value（非显示文本）；多选框可一次选多个值</p>
    </el-form-item>
    <!-- custom：自定义动作模板引用 + 传参 -->
    <template v-else-if="st.action === 'custom'">
      <el-form-item label="动作模板" required>
        <el-select v-model="st.custom_id" filterable clearable placeholder="选择自定义动作（动作库页维护）" style="width: 100%">
          <el-option v-for="ca in customActions" :key="ca.id" :value="ca.id"
                     :label="ca.description ? `${ca.name}（${ca.description}）` : ca.name" />
        </el-select>
        <p class="tip action-tip">{{ selectedCustom?.description || '项目级 JS 模板：脚本入参 args，return 值进 facts.result' }}</p>
      </el-form-item>
      <el-form-item label="传参 args">
        <div class="ds-menu-row">
          <el-input v-model="st.value" placeholder="传给脚本的参数（脚本内以 args 访问），支持 ${变量}" @focus="valIns.onSqlFocus" />
          <DatasetVarMenu :sheets="dsSheets" @insert="valIns.onSqlInsert" />
        </div>
      </el-form-item>
    </template>
    <!-- 合并参数：click_text 匹配方式 / click 模式 / confirm 形态 -->
    <el-form-item v-if="st.action === 'click_text'" label="同名序号">
      <el-input-number v-model="clickIndex" :min="0" :step="1" controls-position="right" style="width: 120px" />
      <span class="tip inline-tip">同名按钮取第 N 个（0 起）；费用表两个「新增标准费用」取第 2 个填 1</span>
    </el-form-item>
    <el-form-item v-if="st.action === 'click_text'" label="匹配方式">
      <el-radio-group v-model="clickMatch">
        <el-radio-button value="exact">精确（默认）</el-radio-button>
        <el-radio-button value="contains">包含</el-radio-button>
      </el-radio-group>
      <p class="tip action-tip">包含匹配：填「导入」可点到「导入报关费用」</p>
    </el-form-item>
    <el-form-item v-if="st.action === 'click_text'" label="无则跳过">
      <el-switch v-model="clickOptional" />
      <span class="tip inline-tip">按钮可能不存在时（如「作废」仅有生效单证才出现）跳过不报错，result=absent</span>
    </el-form-item>
    <!-- toast_watch：反向断言（不得出现）/ 宽容（超时不报错），二者互斥 -->
    <template v-if="st.action === 'toast_watch'">
      <el-form-item label="反向断言">
        <el-switch v-model="toastAbsent" />
        <span class="tip inline-tip">观察窗（步骤超时）内出现提示即失败；开启后文本可空=任何提示都算命中</span>
      </el-form-item>
      <el-form-item label="无则跳过">
        <el-switch v-model="toastOptional" />
        <span class="tip inline-tip">超时未出现返回 no-toast 不报错（配「无则跳过」点击的条件场景）</span>
      </el-form-item>
    </template>
    <el-form-item v-if="st.action === 'click'" label="点击模式">
      <el-radio-group v-model="clickMode">
        <el-radio-button value="default">普通</el-radio-button>
        <el-radio-button value="js">JS 直调</el-radio-button>
      </el-radio-group>
      <p class="tip action-tip">JS 直调绕过可点击性校验（被遮挡/固定列副本区/动画中元素，原 js_click）</p>
    </el-form-item>
    <template v-if="st.action === 'confirm'">
      <el-form-item label="轮询等待">
        <el-switch v-model="confirmWait" />
        <span class="tip inline-tip">弹窗延迟数秒出现时持续监视并点击</span>
      </el-form-item>
      <el-form-item label="无则跳过">
        <el-switch v-model="confirmOptional" />
        <span class="tip inline-tip">只点「继续提交」类按钮，无弹窗不报错</span>
      </el-form-item>
    </template>
    <el-form-item label="超时时间">
      <el-input-number v-model="timeoutMs" :min="0" :step="1000" controls-position="right" style="width: 180px" />
      <span class="wait-unit">ms</span>
      <p class="tip wait-tip">本步骤元素定位/页面加载的超时上限，默认 15000ms。</p>
    </el-form-item>
    <el-form-item v-if="st.action === 'click'" label="强制点击">
      <el-switch v-model="st.force" />
      <span class="tip inline-tip">跳过元素可见性/可点击性校验（遮挡场景使用）</span>
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
import { UI_ACTIONS, UI_ACTION_ORIGINS, STRATEGY_OPTIONS, ELEMENT_ACTIONS, ELEMENT_REQUIRED_ACTIONS, TEXT_VALUE_ACTIONS, TEXT_VALUE_META } from '@/utils/ui'
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
  /** 页面域 scope → 中文名（元素库页维护）：下拉/回显显示中文而非裸编码 */
  scopeLabels?: Record<string, string>
  /** 节点页面域（编排改造：节点=页面域）：固定元素可选范围，不传则步骤内自选域 */
  nodeScope?: string
}>()

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
const textValueTip = computed(() => TEXT_VALUE_META[st.value.action]?.tip || '')

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

/** select_option 的多值输入 / wait 的时长 / click_text 序号与匹配 / click 模式 / confirm 形态（与 step 字段互转） */
const optionValues = ref<string[]>([])
const waitValue = ref<number>(1000)
const clickIndex = ref<number>(0)
const clickMatch = ref<'exact' | 'contains'>('exact')
const clickOptional = ref(false)
const toastAbsent = ref(false)
const toastOptional = ref(false)
const clickMode = ref<'default' | 'js'>('default')
const confirmWait = ref(false)
const confirmOptional = ref(false)
const timeoutMs = computed<number>({
  get: () => st.value.timeout_ms ?? 15000,
  set: (v: number) => { st.value.timeout_ms = v },
})

function elementLabel(el: UiElement): string {
  return el.description ? `${el.element_key}（${el.description}）` : el.element_key
}

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

/** 多行描述取首行（下拉 label 单行展示） */
function firstLine(text?: string | null): string {
  return (text || '').split('\n')[0].slice(0, 30)
}

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
  if (p.action !== 'click') p.force = undefined
  if (p.action !== 'custom') p.custom_id = undefined
  return null
}

defineExpose({ collect })
</script>

<style scoped>
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
/* 动作下拉项：名称 + 标识 + 来源标签 */
.action-opt {
  display: flex;
  align-items: center;
  gap: 8px;
}
.action-opt-name {
  font-weight: 500;
}
.action-opt-code {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-faint);
}
.action-opt-tag {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 3px 7px;
  border-radius: 8px;
}
.action-opt-tag.origin-native {
  color: #2563eb;
  background: rgba(37, 99, 235, 0.12);
}
.action-opt-tag.origin-wrapped {
  color: #b45309;
  background: rgba(180, 83, 9, 0.12);
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
