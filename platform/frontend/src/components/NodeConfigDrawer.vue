<template>
  <el-drawer
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="节点配置"
    size="min(780px, 92vw)"
    direction="rtl"
    class="node-config-drawer"
    destroy-on-close
  >
    <el-tabs v-if="draft" v-model="activeTab" class="node-config-tabs">
      <el-tab-pane label="基础配置" name="basic">
        <!-- UI 节点：浏览器操作表单（step_type='ui'） -->
        <el-form v-if="isUiNode" label-width="90px">
          <el-form-item label="节点ID">
            <el-input :model-value="draft.node_id" disabled />
          </el-form-item>
          <el-form-item label="页面动作">
            <div class="steps-wrap">
              <!-- 工具行：计数 + 过滤定位 + 添加 -->
              <div class="steps-toolbar">
                <span class="steps-count">共 {{ uiSteps.length }} 个动作</span>
                <el-input
                  v-model="filterText"
                  size="small"
                  clearable
                  style="width: 200px"
                  placeholder="按动作/参数过滤定位"
                >
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
                <el-dropdown trigger="click" @command="addStep">
                  <el-button size="small" type="primary" plain>+ 添加动作</el-button>
                  <template #dropdown>
                    <el-dropdown-menu class="action-add-menu">
                      <el-dropdown-item v-for="a in UI_ACTIONS" :key="a.action" :command="a.action">
                        {{ a.name }}（{{ a.action }}）
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
              <!-- 紧凑动作行：单行摘要，点击展开编辑（手风琴，同时只展开一个） -->
              <div class="steps-list">
                <div
                  v-for="(st, i) in uiSteps"
                  :key="i"
                  v-show="matchStep(st)"
                  class="step-row"
                  :class="{ open: openIdx === i }"
                >
                  <div class="step-line" :title="`${uiActionName(st.action)}：${stepBrief(st)}`" @click="toggleStep(i)">
                    <span class="step-no">{{ i + 1 }}</span>
                    <span class="step-tag">{{ uiActionName(st.action) }}</span>
                    <span class="step-brief">{{ stepBrief(st) || '— 未配置 —' }}</span>
                    <span class="step-ops" @click.stop>
                      <el-button link size="small" :disabled="i === 0" @click="moveStep(i, -1)">↑</el-button>
                      <el-button link size="small" :disabled="i === uiSteps.length - 1" @click="moveStep(i, 1)">↓</el-button>
                      <el-button link type="danger" size="small" :disabled="uiSteps.length <= 1" @click="removeStep(i)">删</el-button>
                    </span>
                    <el-icon class="step-arrow" :class="{ expanded: openIdx === i }"><ArrowDown /></el-icon>
                  </div>
                  <div v-if="openIdx === i" class="step-edit">
                    <UiActionForm :ref="(el: any) => (stepFormRefs[i] = el)" :step="st" :ui-elements="uiElements" :custom-actions="customActions" :action-docs="actionDocs" :ds-sheets="dsSheets" :scope-labels="scopeLabels" />
                  </div>
                </div>
                <div v-if="!uiSteps.some(matchStep)" class="steps-empty">没有匹配「{{ filterText }}」的动作</div>
              </div>
              <p class="tip steps-tip">
                单行摘要点击展开编辑；几十个动作建议配合上方过滤框定位。
                <a class="action-doc-link" @click.prevent="store.openCoreCapability('actions')">查看动作解析 →</a>
              </p>
            </div>
          </el-form-item>
          <el-form-item label="等待时间">
            <el-input-number
              v-model="waitAfterMs"
              :min="0"
              :step="500"
              :step-strict="false"
              controls-position="right"
              style="width: 180px"
            />
            <span class="wait-unit">ms</span>
            <p class="tip wait-tip">本节点全部动作完成后、下一节点前的等待间隔。默认 0（不等待）。</p>
          </el-form-item>
        </el-form>
        <!-- API 节点：原有接口绑定表单 -->
        <el-form v-else label-width="90px">
          <el-form-item label="节点ID">
            <el-input :model-value="draft.node_id" disabled />
          </el-form-item>
          <el-form-item label="绑定接口">
            <!-- 接口注册面已裁撤：无可选清单，仅回显历史 api_id；等待/提取/断言仍可调整 -->
            <el-input :model-value="draft.api_id ? `接口 #${draft.api_id}（历史 API 节点）` : '未绑定'" disabled />
          </el-form-item>
          <el-form-item label="等待时间">
            <el-input-number
              v-model="waitAfterMs"
              :min="0"
              :step="500"
              :step-strict="false"
              controls-position="right"
              style="width: 180px"
            />
            <span class="wait-unit">ms</span>
            <p class="tip wait-tip">当前接口执行完成后、下一个接口请求前的等待间隔，给后端处理事务/数据落库留出时间。默认 0（不等待）。</p>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="后置提取" name="extract">
        <PostExtractTable v-model="draft.post_extract" :ref-groups="refGroups" />
        <p v-if="isUiNode" class="tip">UI 步骤的提取对页面事实（facts）求值：<code>source=response</code> + JSONPath，如 <code>$.url</code>、<code>$.text</code>、<code>$.title</code>。</p>
        <p v-else class="tip">提取的变量存入本节点命名空间，供后续节点按 <code>{{ SQL_BRACE }}</code>（SQL 内）或引用来源（参数取值）引用。</p>
      </el-tab-pane>

      <el-tab-pane label="断言规则" name="assert">
        <AssertionTable v-model="draft.assertions" :ref-groups="refGroups" />
        <div class="tip-with-help">
          <p v-if="isUiNode" class="tip">UI 步骤断言对 facts 求值（如 <code>$.url</code> contains、<code>$.text</code> equals）；DB 断言可直接使用。</p>
          <p v-else class="tip">DB 断言 SQL 可用 <code>{{ SQL_BRACE }}</code> 引用已提取变量；期望值支持四来源。</p>
          <el-button text size="small" class="help-link" @click="store.openCoreCapability('assertion')">
            <el-icon><QuestionFilled /></el-icon> 查看断言规则
          </el-button>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <!-- 双层保存语义：此处仅应用到画布，持久化需再点画布右上「保存用例」 -->
      <el-button type="primary" @click="onSave">应用配置</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled, Search, ArrowDown } from '@element-plus/icons-vue'
import PostExtractTable from './PostExtractTable.vue'
import AssertionTable from './AssertionTable.vue'
import UiActionForm from './UiActionForm.vue'
import DatasetVarMenu, { type DsVarSheet } from './DatasetVarMenu.vue'
import { useAppStore } from '@/stores'
import { elementApi, customActionApi, uiActionDocApi, caseApi, scopeLabelApi, type NodeConfig, type UiElement, type UiStep, type CustomAction, type UiActionDoc } from '@/api'
import type { RefVarGroup } from './VarRefSelect.vue'
import { UI_ACTIONS, uiActionName, validateUiStepData } from '@/utils/ui'

const store = useAppStore()

const props = defineProps<{
  visible: boolean
  config: NodeConfig
  refGroups?: RefVarGroup[]
  /** 归属用例（UI 动作值的 ${sheet.字段} 插入器懒加载绑定数据集用） */
  caseId?: number
  /** 用例绑定的数据集 id（运行时只注入该数据集的 sheet，选择器不提供其它数据集） */
  boundDatasetId?: number | null
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'save', config: NodeConfig): void
}>()

// SQL 占位语法字面量（含 }}，不能内嵌进模板插值表达式，经此常量输出）
const SQL_BRACE = '{{节点.变量}}'

const activeTab = ref('basic')

// 编辑草稿：打开抽屉时深拷贝一份，避免直接 mutate 父组件引用导致
// 「关闭即生效、保存按钮无实义」的假保存语义；取消即丢弃草稿。
const draft = ref<NodeConfig | null>(null)
const isUiNode = computed(() => draft.value?.step_type === 'ui')
// 动作序列（打开抽屉时已规范化保证 steps 存在）
const uiSteps = computed<UiStep[]>(() => draft.value!.ui_params!.steps!)
// 各步骤表单实例（collect 收敛校验；手风琴只挂载展开中的步骤）
const stepFormRefs = ref<any[]>([])
// 手风琴：当前展开编辑的步骤下标（-1 全折叠）；过滤定位关键字
const openIdx = ref(-1)
const filterText = ref('')

// 元素库数据（一次全量加载，组内各步骤共享）
const uiElements = ref<UiElement[]>([])
let uiElementsLoaded = false
// 页面域中文名映射（scope → label）：页面域下拉/摘要显示中文而非裸 scope 编码
const scopeLabels = ref<Record<string, string>>({})
let scopeLabelsLoaded = false
// 自定义动作模板（一次加载，custom 步骤下拉用）
const customActions = ref<CustomAction[]>([])
let customActionsLoaded = false
// 动作描述覆盖（动作库管理 → 编辑描述；wrapped 动作下拉提示显示覆盖文本）
const actionDocs = ref<UiActionDoc[]>([])
let actionDocsLoaded = false
// 绑定数据集的 sheet 清单（${sheet.字段} 插入器数据源；只取绑定数据集——
// 运行时只注入绑定/选中数据集的 sheet，选择器不得提供其它数据集的 label）。
// 按 caseId 记忆已加载：换用例重拉，同用例抽屉反复开关不重复请求
const dsSheets = ref<DsVarSheet[]>([])
let dsSheetsLoadedCase: number | null = null

async function loadDsSheets() {
  if (!props.caseId) return
  if (dsSheetsLoadedCase === props.caseId) return
  dsSheetsLoadedCase = props.caseId
  dsSheets.value = []
  if (!props.boundDatasetId) return  // 未绑定数据集：不提供插入器（不报错，静默无按钮）
  try {
    const list = await caseApi.datasets(props.caseId)
    const bound = list.find((d) => d.id === props.boundDatasetId)
    dsSheets.value = (bound?.rows || []).map((r) => ({
      label: r.label || `Sheet${r.row_index}`,
      fields: Object.keys(r.data || {})
        .filter((k) => k !== 'nodes')
        .map((name) => ({ name, desc: (r.field_desc || {})[name] || '' })),
    }))
  } catch {
    dsSheets.value = []  // 数据集加载失败仅影响插入器，静默降级
  }
}

async function loadUiElements() {
  if (uiElementsLoaded || !store.currentProjectId) return
  try {
    uiElements.value = await elementApi.list(store.currentProjectId)
    uiElementsLoaded = true
  } catch (e: any) {
    ElMessage.warning(`元素库加载失败：${e.message || '请稍后重试'}（可切「自定义」定位）`)
  }
}

async function loadScopeLabels() {
  if (scopeLabelsLoaded || !store.currentProjectId) return
  try {
    scopeLabels.value = await scopeLabelApi.getMap(store.currentProjectId)
    scopeLabelsLoaded = true
  } catch {
    scopeLabels.value = {}  // 中文映射加载失败回落裸 scope 编码，静默降级
  }
}

async function loadCustomActions() {
  if (customActionsLoaded || !store.currentProjectId) return
  try {
    customActions.value = await customActionApi.list(store.currentProjectId)
    customActionsLoaded = true
  } catch {
    customActions.value = []  // 自定义动作加载失败仅影响 custom 步骤选择，静默降级
  }
}

async function loadActionDocs() {
  if (actionDocsLoaded || !store.currentProjectId) return
  try {
    actionDocs.value = await uiActionDocApi.list(store.currentProjectId)
    actionDocsLoaded = true
  } catch {
    actionDocs.value = []  // 覆盖描述加载失败回落内置文案，静默降级
  }
}

/** 步骤单行摘要：定位目标 + 关键参数（列表行展示，tooltip 看全文）。
 * 元素显示中文描述优先（element_key 兜底）——2026-10-28：此前裸显 元素#163
 * 系元素库重建后引用悬空，现修复悬空并让摘要直读中文 */
function stepBrief(st: UiStep): string {
  const el = st.element
  const elTxt = el?.element_id
    ? (() => {
        const found = uiElements.value.find((x) => x.id === el.element_id)
        return found ? (found.description || found.element_key) : `元素#${el.element_id}（库中不存在，请重选）`
      })()
    : (el?.value ? `${el.strategy || 'css'}=${el.value}` : '')
  const v = st.value
  switch (st.action) {
    case 'goto': return String(st.url ?? '')
    case 'save': return String(v || '保存成功')
    case 'wait': return elTxt ? `等元素 ${elTxt}` : `${Number(v ?? 1000)}ms`
    case 'press': return String(v || 'Enter')
    case 'select_option': return (st.values?.length ? st.values.join(',') : String(v ?? ''))
    case 'custom': {
      const ca = customActions.value.find((x) => x.id === st.custom_id)
      return [ca?.name ?? `模板#${st.custom_id ?? '?'}`, v != null ? String(v) : ''].filter(Boolean).join(' → ')
    }
    default: return [elTxt, v != null ? String(v) : ''].filter(Boolean).join(' → ')
  }
}

/** 过滤匹配：动作中文名/标识/参数摘要含关键字（不区分大小写） */
function matchStep(st: UiStep): boolean {
  const kw = filterText.value.trim().toLowerCase()
  if (!kw) return true
  const hay = [uiActionName(st.action), st.action, stepBrief(st)].join(' ').toLowerCase()
  return hay.includes(kw)
}

/** 展开/折叠步骤：切换前先把旧展开步骤的局部状态收敛回数据（表单即将卸载） */
function toggleStep(i: number) {
  if (openIdx.value === i) {
    stepFormRefs.value[i]?.collect?.()
    openIdx.value = -1
  } else {
    if (openIdx.value >= 0) stepFormRefs.value[openIdx.value]?.collect?.()
    openIdx.value = i
    nextTick(() => {
      document.querySelectorAll<HTMLElement>('.step-row')[i]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  }
}

/** 添加动作（下拉点选）：追加并展开滚动到新步骤 */
function addStep(action: UiStep['action']) {
  if (openIdx.value >= 0) stepFormRefs.value[openIdx.value]?.collect?.()
  uiSteps.value.push({ action })
  openIdx.value = uiSteps.value.length - 1
  filterText.value = ''
  nextTick(() => {
    document.querySelectorAll<HTMLElement>('.step-row')[openIdx.value]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

/** 删除步骤：折叠态下操作，展开态先收敛再删 */
function removeStep(i: number) {
  if (openIdx.value === i) {
    openIdx.value = -1
  } else if (openIdx.value > i) {
    openIdx.value -= 1
  }
  uiSteps.value.splice(i, 1)
  stepFormRefs.value.splice(i, 1)
}

/** 上移/下移步骤 */
function moveStep(i: number, delta: number) {
  const j = i + delta
  if (j < 0 || j >= uiSteps.value.length) return
  const wasOpen = openIdx.value
  if (wasOpen === i) stepFormRefs.value[i]?.collect?.()
  const [item] = uiSteps.value.splice(i, 1)
  uiSteps.value.splice(j, 0, item)
  stepFormRefs.value.splice(i, 1)
  openIdx.value = wasOpen === i ? j : (wasOpen === j ? i : wasOpen)
}

watch(
  () => props.visible,
  async (v) => {
    if (!v) return
    const d: NodeConfig = JSON.parse(JSON.stringify(props.config))
    // UI 节点规范化：统一为动作序列 steps；旧单动作节点（顶层 action）迁移为单步组
    if (d.step_type === 'ui') {
      if (!d.ui_params) d.ui_params = { steps: [{ action: 'goto' }] }
      if (!Array.isArray(d.ui_params.steps) || !d.ui_params.steps.length) {
        const single: UiStep = {
          action: (d.ui_params.action as UiStep['action']) || 'click',
          ...(d.ui_params.url != null ? { url: d.ui_params.url } : {}),
          ...(d.ui_params.element ? { element: d.ui_params.element } : {}),
          ...(d.ui_params.value != null ? { value: d.ui_params.value } : {}),
          ...(d.ui_params.values != null ? { values: d.ui_params.values } : {}),
          ...(d.ui_params.timeout_ms != null ? { timeout_ms: d.ui_params.timeout_ms } : {}),
          ...(d.ui_params.wait_for ? { wait_for: d.ui_params.wait_for } : {}),
          ...(d.ui_params.force != null ? { force: d.ui_params.force } : {}),
          ...(d.ui_params.files ? { files: d.ui_params.files } : {}),
          ...(d.ui_params.index != null ? { index: d.ui_params.index } : {}),
        }
        d.ui_params = { steps: [single] }
      }
      draft.value = d
      stepFormRefs.value = []
      openIdx.value = -1
      filterText.value = ''
      await Promise.all([loadUiElements(), loadCustomActions(), loadActionDocs(), loadDsSheets(), loadScopeLabels()])
    } else {
      draft.value = d
    }
  },
  { immediate: true },
)

// 当前节点绑定接口的请求字段说明已随「入参来源/前置处理」两 tab 迁至数据集页（入参唯一收敛）

// 节点间等待时间（ms），默认 0；用 computed 兼容旧数据未携带该字段的情况
const waitAfterMs = computed<number>({
  get: () => draft.value?.wait_after_ms ?? 0,
  set: (v: number) => { if (draft.value) draft.value.wait_after_ms = v },
})

function onSave() {
  if (!draft.value) return
  if (isUiNode.value) {
    const steps = draft.value.ui_params!.steps!
    if (!steps.length) {
      ElMessage.warning('动作组至少需要一个动作')
      return
    }
    // 展开中的步骤先收敛局部状态（elementMode/多值/时长等写回数据）
    if (openIdx.value >= 0) stepFormRefs.value[openIdx.value]?.collect?.()
    // 全量数据校验（折叠步骤无表单实例，走数据级校验兜底）
    for (let i = 0; i < steps.length; i++) {
      const err = validateUiStepData(steps[i])
      if (err) {
        ElMessage.warning(`步骤 ${i + 1}（${uiActionName(steps[i].action)}）：${err}`)
        openIdx.value = i
        nextTick(() => {
          document.querySelectorAll<HTMLElement>('.step-row')[i]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
        return
      }
    }
    // 固化为组形态：顶层仅保留 steps（后端 steps 优先）
    draft.value.ui_params = { steps: JSON.parse(JSON.stringify(steps)) }
  } else if (!draft.value.api_id) {
    // api 节点仍要求绑定接口（UI 节点不绑 api_id）
    ElMessage.warning('请先绑定接口，未绑定接口的节点不会执行')
    return
  }
  emit('save', JSON.parse(JSON.stringify(draft.value)))
  emit('update:visible', false)
  ElMessage.success('已应用到画布；点右上角「保存用例」持久化')
}
</script>

<style scoped>
.tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
}
.tip code {
  background: var(--app-hover);
  padding: 1px 5px;
  border-radius: var(--app-radius-xs);
}
.tip-with-help {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.tip-with-help .tip {
  margin-top: 0;
  flex: 1;
  min-width: 0;
}
.help-link {
  flex-shrink: 0;
  color: var(--app-primary);
  padding: 0;
  height: auto;
}
.help-link .el-icon {
  margin-right: 4px;
  font-size: 14px;
}
.help-link:hover {
  opacity: 0.8;
}
.wait-unit {
  margin-left: 8px;
  color: var(--app-text-muted);
  font-size: 13px;
}
.wait-tip {
  margin-top: 6px;
  margin-bottom: 0;
}
/* 表单项内的行内提示/动作说明（紧贴控件，不占独立段距） */
.action-tip {
  margin-top: 4px;
  margin-bottom: 0;
  width: 100%;
}
/* 跳转帮助中心「动作解析」tab 的链接 */
.action-doc-link {
  margin-left: 8px;
  color: var(--app-primary);
  cursor: pointer;
  white-space: nowrap;
}
.action-doc-link:hover {
  text-decoration: underline;
}
/* 动作序列编辑器（紧凑行 + 手风琴展开 + 局部滚动） */
.steps-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.steps-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.steps-count {
  font-size: 12px;
  color: var(--app-text-muted);
  flex-shrink: 0;
}
.steps-list {
  max-height: min(46vh, 420px);
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-card);
}
.step-row {
  border-bottom: 1px solid var(--app-border);
}
.step-row:last-child {
  border-bottom: none;
}
.step-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 2px 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.step-line:hover {
  background: var(--app-hover);
}
.step-row.open .step-line {
  background: var(--app-active);
}
.step-no {
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  background: var(--app-hover);
  font-size: 11px;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.step-row.open .step-no {
  background: var(--app-primary);
  color: #fff;
}
.step-tag {
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-brief {
  flex: 1;
  min-width: 0;
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-ops {
  display: flex;
  gap: 0;
  flex-shrink: 0;
  opacity: 0.25;
  transition: opacity 0.15s;
}
.step-line:hover .step-ops,
.step-row.open .step-ops {
  opacity: 1;
}
.step-arrow {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--app-text-faint);
  transition: transform 0.2s;
}
.step-arrow.expanded {
  transform: rotate(180deg);
}
.step-edit {
  padding: 8px 12px 6px;
  border-top: 1px dashed var(--app-border);
  background: var(--app-hover);
}
.steps-empty {
  padding: 14px;
  text-align: center;
  font-size: 12px;
  color: var(--app-text-faint);
}
.steps-tip {
  margin: 2px 0 0;
}
.action-add-menu {
  max-height: 320px;
  overflow-y: auto;
}
.inline-tip {
  margin: 0 0 0 10px;
  display: inline;
}
</style>

<!-- el-drawer teleport 到 body，scoped 无法命中外层元素，需用全局样式 -->
<style>
/* drawer body 改为 flex 布局：tabs header 固定，content 区域独立滚动 */
.node-config-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}
/* tabs 占满 body 高度 */
.node-config-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
/* tabs header 固定在顶部 */
.node-config-tabs > .el-tabs__header {
  flex-shrink: 0;
  margin-bottom: 0;
  padding: 0 20px;
}
/* tab content 区域独立滚动 */
.node-config-tabs > .el-tabs__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
/* 自定义滚动条 */
.node-config-tabs > .el-tabs__content::-webkit-scrollbar {
  width: 8px;
}
.node-config-tabs > .el-tabs__content::-webkit-scrollbar-track {
  background: transparent;
}
.node-config-tabs > .el-tabs__content::-webkit-scrollbar-thumb {
  background: var(--app-border);
  border-radius: 4px;
}
.node-config-tabs > .el-tabs__content::-webkit-scrollbar-thumb:hover {
  background: var(--app-text-muted);
}
</style>
