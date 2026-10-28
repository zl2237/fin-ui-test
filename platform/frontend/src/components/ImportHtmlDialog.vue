<template>
  <el-dialog
    :model-value="visible"
    title="批量导入元素"
    width="min(960px, 92vw)"
    align-center
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-alert type="info" :closable="false" class="guide">
      <div class="guide-line">两种格式自动识别：业务系统页面 <b>F12 → Copy outerHTML</b>（推荐，解析全部输入框/按钮/勾选框）；或 autotest-playwright 的 <b>locator JSON</b> 原文</div>
      <div class="guide-line">粘贴后点「解析预览」：勾选保留项、改 key、补中文含义后导入（<b>同域同 key 覆盖</b>；HTML 模式自动剔除浮层与隐藏元素）</div>
      <div class="guide-line">HTML 也支持粘贴 .vue 模板源码（识别 <code>@click</code> 行为节点）；hash 命名的候选无稳定语义锚点，默认不勾选</div>
    </el-alert>

    <el-form label-width="70px" inline class="scope-form">
      <el-form-item label="页面域" required>
        <el-input v-model="scope" placeholder="元素归属页面域，如 ordermanage/business_order_add" style="width: 420px" />
      </el-form-item>
    </el-form>

    <el-input
      v-model="htmlText"
      type="textarea"
      :rows="7"
      class="mono html-area"
      placeholder="粘贴页面 HTML（F12 → Copy outerHTML）或 locator JSON 原文，自动识别"
    />

    <div class="parse-bar">
      <el-button type="primary" :loading="parsing" @click="onParse">解析预览</el-button>
      <span v-if="result && result.ok" class="stat">
        已识别：{{ modeLabel }} · 共 {{ elements.length }} 个候选，已选 {{ selectedRows.length }}
        <template v-if="noStrategyCount">；{{ noStrategyCount }} 个无策略字段已跳过</template>
        <template v-if="skippedSum">；跳过：隐藏 {{ result.skipped.hidden }} · 浮层 {{ result.skipped.display_only }} · 范围合并 {{ result.skipped.merged }}</template>
      </span>
      <span v-else-if="result && !result.ok" class="stat err">{{ result.error }}</span>
    </div>

    <template v-if="elements.length">
      <div class="table-bar">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="all">全部 {{ elements.length }}</el-radio-button>
          <el-radio-button value="input">输入 {{ countOf('input') }}</el-radio-button>
          <el-radio-button value="button">按钮 {{ countOf('button') }}</el-radio-button>
          <el-radio-button value="other">其他 {{ countOf('other') }}</el-radio-button>
        </el-radio-group>
        <div class="table-bar-right">
          <el-button size="small" @click="selectAllVisible">全选本组</el-button>
          <el-button size="small" @click="clearAll">清空勾选</el-button>
        </div>
      </div>

      <el-table
        ref="tableRef"
        :data="filteredElements"
        size="small"
        max-height="380"
        row-key="uid"
        border
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" reserve-selection />
        <el-table-column label="元素 Key" min-width="230">
          <template #default="{ row }">
            <div class="key-cell">
              <el-input v-model="row.element_key" size="small" :class="{ 'key-invalid': keyError(row) }" />
              <div class="key-tags">
                <el-tag v-if="existingKeys.has(row.element_key)" size="small" type="warning">将覆盖</el-tag>
                <el-tag v-else-if="(keyCounts.get(row.element_key) || 0) > 1" size="small" type="danger">域内重复</el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="中文含义" min-width="170">
          <template #default="{ row }">
            <el-input v-model="row.description" size="small" placeholder="如 提单号输入框" />
          </template>
        </el-table-column>
        <el-table-column label="类型" width="66" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="categoryTag(row.category)">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="命名" width="76" align="center">
          <template #default="{ row }">
            <el-tooltip :disabled="row.key_origin !== 'hash'" content="无语义锚点，路径哈希命名——建议人工改名" placement="top">
              <el-tag size="small" :type="row.key_origin === 'hash' ? 'danger' : 'info'">{{ originLabel(row.key_origin) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="定位策略（tooltip 查看完整 xpath）" min-width="230">
          <template #default="{ row }">
            <el-tooltip placement="top" popper-class="app-tip">
              <template #content>
                <div v-for="(v, k) in row.strategies" :key="k">{{ k }} = {{ v }}</div>
                <div>full_xpath = {{ row.full_xpath }}</div>
                <div v-if="row.dup_strategy">与其他候选语义策略相同（如多行同名按钮），注意区分</div>
              </template>
              <span class="mono strat-brief" :class="{ 'strat-dup': row.dup_strategy }">
                {{ strategyBrief(row) }}<el-tag v-if="row.dup_strategy" size="small" type="danger" class="dup-tag">重复</el-tag>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="来源" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono source-brief">{{ row.source }}</span>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :disabled="!selectedRows.length" :loading="submitting" @click="onImport">
        导入{{ selectedRows.length ? ` ${selectedRows.length} 个` : '' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 元素库批量导入弹窗：粘贴内容自动嗅探格式——
 * - HTML 片段（F12 Copy outerHTML / .vue 模板）：utils/parseHtmlElements 解析出候选
 * - locator JSON（{key:{策略字段,description}}）：展开为候选
 * 统一走预览表格人工勾选/改 key/补中文含义 → elementApi.batch 覆盖式入库。
 * row-key 用解析产出的 uid（行内会改 element_key，用它勾选会错乱）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { elementApi } from '@/api'
import { useAppStore } from '@/stores'
import { parseHtmlElements, type ParsedElement } from '@/utils/parseHtmlElements'

const props = defineProps<{ visible: boolean; defaultScope: string }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'imported'): void }>()

const store = useAppStore()

const scope = ref('')
const htmlText = ref('')
const parsing = ref(false)
const submitting = ref(false)
const elements = ref<ParsedElement[]>([])
const result = ref<ReturnType<typeof parseHtmlElements> | null>(null)
const filter = ref<'all' | 'input' | 'button' | 'other'>('all')
const existingKeys = ref<Set<string>>(new Set())
const selectedRows = ref<ParsedElement[]>([])
const tableRef = ref<{ toggleRowSelection: (row: ParsedElement, selected?: boolean) => void }>()
/** 嗅探出的导入格式（html / locator_json），控制提示文案与 hash 默认不勾策略 */
const mode = ref<'html' | 'locator_json'>('html')
const noStrategyCount = ref(0)

const modeLabel = computed(() => (mode.value === 'html' ? 'HTML 片段' : 'locator JSON'))

const skippedSum = computed(() => {
  if (mode.value !== 'html') return 0
  const s = result.value?.skipped
  return s ? s.hidden + s.display_only + s.merged : 0
})

const filteredElements = computed(() =>
  filter.value === 'all' ? elements.value : elements.value.filter((e) => e.category === filter.value),
)

function countOf(c: 'input' | 'button' | 'other') {
  return elements.value.filter((e) => e.category === c).length
}

// key 实时校验（小写字母开头，仅小写字母/数字/下划线）
const KEY_RE = /^[a-z][a-z0-9_]{0,63}$/
function keyError(row: ParsedElement): boolean {
  return !KEY_RE.test(row.element_key)
}

/** 域内重复计数（含行内改名后的实时值） */
const keyCounts = computed(() => {
  const m = new Map<string, number>()
  for (const e of elements.value) m.set(e.element_key, (m.get(e.element_key) || 0) + 1)
  return m
})

function categoryLabel(c: string) {
  return c === 'input' ? '输入' : c === 'button' ? '按钮' : '其他'
}

const ORIGIN_LABELS: Record<string, string> = { testid: 'testid', name: 'name', id: 'id', pinyin: '拼音', hash: 'hash', manual: '人工' }
function originLabel(o: string) {
  return ORIGIN_LABELS[o] || o
}
function categoryTag(c: string) {
  return c === 'input' ? 'success' : c === 'button' ? 'primary' : 'info'
}

function strategyBrief(row: ParsedElement): string {
  const parts = Object.entries(row.strategies).map(([k, v]) => `${k}=${v}`)
  const brief = parts.join(' · ') || '仅 full_xpath'
  return brief.length > 60 ? brief.slice(0, 60) + '…' : brief
}

// 打开即重置，页面域带入当前筛选
watch(
  () => props.visible,
  (v) => {
    if (v) {
      scope.value = props.defaultScope
      htmlText.value = ''
      result.value = null
      elements.value = []
      selectedRows.value = []
      filter.value = 'all'
      existingKeys.value = new Set()
      noStrategyCount.value = 0
    }
  },
)

/** locator JSON → 候选行（key 人工已命名；无策略字段的 key 跳过计数） */
function fromLocatorJson(obj: Record<string, unknown>): ParsedElement[] {
  const items: ParsedElement[] = []
  let noStrategy = 0
  let uid = 1
  for (const [key, val] of Object.entries(obj)) {
    if (!key || typeof val !== 'object' || val === null) continue
    const { description, ...strategies } = val as Record<string, unknown>
    const semantic = Object.fromEntries(
      Object.entries(strategies).filter(([, v]) => v != null && v !== '')) as Record<string, string>
    if (!Object.keys(semantic).length) {
      noStrategy++
      continue
    }
    const has = (...ks: string[]) => ks.some((k) => semantic[k] != null)
    items.push({
      uid: uid++,
      element_key: key,
      description: typeof description === 'string' ? description : '',
      category: has('placeholder', 'label', 'for') ? 'input' : has('button', 'text', 'tab') ? 'button' : 'other',
      key_origin: 'manual',
      strategies: semantic,
      full_xpath: typeof semantic.full_xpath === 'string' ? semantic.full_xpath : '',
      source: Object.keys(semantic).join(','),
    })
  }
  noStrategyCount.value = noStrategy
  return items
}

async function onParse() {
  if (!htmlText.value.trim()) {
    ElMessage.warning('请先粘贴页面 HTML 或 locator JSON')
    return
  }
  if (!scope.value.trim()) {
    ElMessage.warning('请填写页面域')
    return
  }
  parsing.value = true
  try {
    // 粘贴内容可达数百 KB，解析放 requestAnimationFrame 让按钮先转起来
    await new Promise((r) => requestAnimationFrame(r))
    const text = htmlText.value.trim()
    let rows: ParsedElement[] = []
    if (text.startsWith('{')) {
      // locator JSON 模式：{ "key": { 策略字段, description } }
      mode.value = 'locator_json'
      let obj: unknown
      try {
        obj = JSON.parse(text)
      } catch {
        result.value = { ok: false, error: '以 { 开头但 JSON 解析失败，请粘贴合法 locator JSON 原文', elements: [], skipped: { hidden: 0, display_only: 0, merged: 0 } }
        return
      }
      if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
        result.value = { ok: false, error: 'locator JSON 需为对象：{ "key": { 策略字段, description } }', elements: [], skipped: { hidden: 0, display_only: 0, merged: 0 } }
        return
      }
      rows = fromLocatorJson(obj as Record<string, unknown>)
      result.value = { ok: true, elements: rows, skipped: { hidden: 0, display_only: 0, merged: 0 } }
      if (!rows.length && !noStrategyCount.value) {
        result.value = { ok: false, error: '未解析到有效元素（key 下至少需要一个策略字段）', elements: [], skipped: { hidden: 0, display_only: 0, merged: 0 } }
        return
      }
    } else {
      // HTML 片段模式
      mode.value = 'html'
      const res = parseHtmlElements(text)
      result.value = res
      if (!res.ok) return
      rows = res.elements
    }
    elements.value = rows.map((e) => ({ ...e }))
    // 预取当前域已有 key：预览「将覆盖」标记
    if (store.currentProjectId) {
      try {
        const existing = await elementApi.list(store.currentProjectId, scope.value.trim())
        existingKeys.value = new Set(existing.map((e) => e.element_key))
      } catch {
        existingKeys.value = new Set() // 预检失败不阻塞导入
      }
    }
    // 默认全选；HTML 模式下无任何语义策略的 hash 候选默认不勾
    await nextTick()
    for (const row of elements.value) {
      tableRef.value?.toggleRowSelection(
        row, !(mode.value === 'html' && row.key_origin === 'hash' && !Object.keys(row.strategies).length))
    }
  } finally {
    parsing.value = false
  }
}

function onSelectionChange(rows: ParsedElement[]) {
  selectedRows.value = rows
}

function selectAllVisible() {
  for (const row of filteredElements.value) tableRef.value?.toggleRowSelection(row, true)
}

function clearAll() {
  for (const row of elements.value) tableRef.value?.toggleRowSelection(row, false)
}

async function onImport() {
  if (!store.currentProjectId) return
  if (!scope.value.trim()) {
    ElMessage.warning('请填写页面域')
    return
  }
  const rows = selectedRows.value
  if (!rows.length) return
  const bad = rows.find((r) => keyError(r))
  if (bad) {
    ElMessage.warning(`key「${bad.element_key}」不合法：小写字母开头，仅小写字母/数字/下划线`)
    return
  }
  const dupInBatch = new Set<string>()
  for (const r of rows) {
    if (dupInBatch.has(r.element_key)) {
      ElMessage.warning(`勾选项中 key「${r.element_key}」重复，请改名后再导入`)
      return
    }
    dupInBatch.add(r.element_key)
  }
  submitting.value = true
  try {
    const res = await elementApi.batch({
      project_id: store.currentProjectId,
      page_scope: scope.value.trim(),
      items: rows.map((r) => {
        // full_xpath 单列字段与策略内字段统一：非空才并入（locator JSON 可能未提供）
        const { full_xpath, ...semantic } = r.strategies as Record<string, string>
        const fx = r.full_xpath || (typeof full_xpath === 'string' ? full_xpath : '')
        return {
          element_key: r.element_key,
          strategies: fx ? { ...semantic, full_xpath: fx } : semantic,
          description: r.description.trim() || undefined,
        }
      }),
    })
    ElMessage.success(res.message)
    emit('imported')
    emit('update:visible', false)
  } catch (e: any) {
    ElMessage.error(e.message || '导入失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.guide {
  margin-bottom: 12px;
}
.guide-line {
  font-size: 12px;
  line-height: 1.8;
}
.scope-form {
  margin-bottom: 2px;
}
.html-area :deep(textarea) {
  font-size: 12px;
}
.parse-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 10px 0 8px;
}
.stat {
  font-size: 12px;
  color: var(--app-text-muted);
}
.stat.err {
  color: var(--el-color-danger);
}
.table-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.key-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.key-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.key-tags {
  min-height: 18px;
}
.strat-brief {
  font-size: 12px;
  color: var(--app-text-muted);
}
.strat-dup {
  color: var(--el-color-danger);
}
.dup-tag {
  margin-left: 4px;
}
.source-brief {
  font-size: 12px;
  color: var(--app-text-muted);
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
