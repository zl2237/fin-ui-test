<template>
  <el-dialog
    :model-value="visible"
    width="min(860px, 92vw)"
    align-center
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <template #header>
      <span>批量导入 sheet<HintTip content="粘贴 Excel 复制区或 CSV：每行一个 sheet（名=首列值）；单列纯值用「字段名」命名" /></span>
    </template>

    <el-input
      v-model="text"
      type="textarea"
      :rows="9"
      class="mono paste-area"
      placeholder="示例（多列，首行=字段名）：&#10;提单号&#9;下单客户名称&#10;UITU00000001&#9;统济机电&#10;UITU00000002&#9;高世阳test&#10;&#10;示例（单列纯值）：&#10;UITU00000001&#10;UITU00000002"
      @input="onTextInput"
    />

    <div class="opts-bar">
      <!-- 多列：首行歧义由勾选框裁决；单列：恒无表头，勾选框无意义，改由「字段名」输入框命名 -->
      <el-checkbox v-if="!isSingleColumn" v-model="firstRowIsHeader" @change="reparse">
        首行是字段名
      </el-checkbox>
      <template v-else>
        <span class="opt-label">字段名</span>
        <el-input v-model="singleField" size="small" style="width: 160px" placeholder="如 bl_no" @input="reparse" />
      </template>
      <!-- 开=覆盖现有 sheet；关=追加到现有之后（效果见解析统计行） -->
      <span class="opt-label">覆盖现有 {{ existingRows.length }} 个 sheet</span>
      <el-switch v-model="overwrite" />
    </div>

    <div class="parse-bar">
      <el-button type="primary" :loading="parsing" @click="onParse">解析预览</el-button>
      <span v-if="parseError" class="stat err">{{ parseError }}</span>
      <span v-else-if="parsed" class="stat">
        已解析 {{ parsed.rows.length }} 个 sheet · 字段：{{ parsed.headers.join('、') }}
        · {{ overwrite ? `覆盖后共 ${parsed.rows.length} 个` : `追加后共 ${existingRows.length + parsed.rows.length} 个` }}
        <template v-if="dupLabelCount">；{{ dupLabelCount }} 个重名已自动加序号</template>
        <template v-if="invalidLabelRows.length">；<span class="err">{{ invalidLabelRows.length }} 个 sheet 名不合规（含 . $ { } 或 __ 前缀）</span></template>
      </span>
    </div>

    <el-table v-if="parsed && parsed.rows.length" :data="parsed.rows" size="small" max-height="300" border>
      <el-table-column label="sheet 名（首列）" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ row.label || '（空，导入时补 行N）' }}</template>
      </el-table-column>
      <el-table-column
        v-for="h in parsed.headers"
        :key="h"
        :label="h"
        min-width="130"
        show-overflow-tooltip
      >
        <template #default="{ row }">{{ row.data[h] }}</template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!parsed || !parsed.rows.length || !!invalidLabelRows.length"
        :loading="saving"
        @click="onImport"
      >
        导入{{ parsed && parsed.rows.length ? ` ${parsed.rows.length} 个 sheet` : '' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 数据集「批量导入」弹窗：粘贴一批数据（Excel 复制/CSV/单列值）→
 * utils/parseSheetPaste 解析成 N 个 sheet → 预览（列=字段名、行=sheet）→
 * 整表替换保存（追加模式把现有行原样拼在前面；现有行的 data 原对象透传，
 * 不经文本往返，JSON 值无损）。重名/空 sheet 名在提交前本地补齐（行N/序号），
 * 后端 label 规则（. $ { } / __ 前缀）本地预检拦截。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { datasetApi, type DataSetSheetIn, type DataSetSheetOut } from '@/api'
import { parseSheetPaste, type SheetPasteParse } from '@/utils/parseSheetPaste'
import HintTip from './HintTip.vue'

const props = defineProps<{
  visible: boolean
  datasetId: number | null
  existingRows: DataSetSheetOut[]
}>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'imported'): void }>()

const text = ref('')
const firstRowIsHeader = ref(true)
const singleField = ref('')
/** 开=覆盖现有 sheet；关=追加到现有之后 */
const overwrite = ref(false)
const parsed = ref<SheetPasteParse | null>(null)
const parseError = ref('')
const parsing = ref(false)
const saving = ref(false)

/** 现有 sheet 的首个字段名（单列场景的智能默认，如 bl_no） */
const existingFirstField = computed(() => {
  const first = props.existingRows[0]
  if (!first) return ''
  const order = first.field_order || []
  const keys = Object.keys(first.data || {}).filter((k) => k !== 'nodes')
  return order.find((k) => keys.includes(k)) || keys[0] || ''
})

const isSingleColumn = computed(() => !/\t/.test(text.value) && !/[,，]/.test(text.value))

/** 提交前 label 终值：空补 行N、与现有/批内重名加序号；返回 label → 行序映射 */
function finalizeLabels(rows: { label: string }[]): string[] {
  const used = new Set<string>(
    !overwrite.value ? props.existingRows.map((r) => r.label) : [])
  const out: string[] = []
  rows.forEach((r, i) => {
    let label = r.label || `行${i + 1}`
    if (used.has(label)) {
      let n = 2
      while (used.has(`${label}${n}`)) n++
      label = `${label}${n}`
    }
    used.add(label)
    out.push(label)
  })
  return out
}

const finalLabels = computed(() => (parsed.value ? finalizeLabels(parsed.value.rows) : []))
const dupLabelCount = computed(() => {
  if (!parsed.value) return 0
  return parsed.value.rows.filter((r, i) => r.label && finalLabels.value[i] !== r.label).length
})
const invalidLabelRows = computed(() =>
  finalLabels.value.filter((l) => /[.${}]/.test(l) || l.startsWith('__')
    || ['nodes', 'context', 'db'].includes(l) || l.length > 100))

function doParse() {
  parseError.value = ''
  if (!text.value.trim()) {
    parsed.value = null
    parseError.value = '先粘贴数据（Excel 复制区域 / CSV / 单列值）'
    return
  }
  parsed.value = parseSheetPaste(text.value, {
    firstRowIsHeader: firstRowIsHeader.value,
    fallbackField: singleField.value,
  })
  if (!parsed.value.rows.length) {
    parseError.value = '未解析到有效数据行'
    parsed.value = null
  }
}

function onParse() {
  parsing.value = true
  doParse()
  setTimeout(() => { parsing.value = false }, 120) // 按钮反馈节拍（解析本身同步瞬完）
}

function reparse() {
  if (parsed.value || parseError.value) doParse()
}

function onTextInput() {
  // 粘贴内容变化后重置解析态；单列/多列切换联动「首行是字段名」默认值
  parsed.value = null
  parseError.value = ''
  firstRowIsHeader.value = !isSingleColumn.value
}

async function onImport() {
  if (!props.datasetId || !parsed.value) return
  const labels = finalLabels.value
  const imported: DataSetSheetIn[] = parsed.value.rows.map((r, i) => ({
    label: labels[i],
    data: r.data,
    field_order: parsed.value!.headers,
  }))
  const existing: DataSetSheetIn[] = !overwrite.value
    ? props.existingRows.map((r) => ({
        label: r.label,
        data: r.data,
        field_desc: r.field_desc ?? undefined,
        field_order: r.field_order ?? undefined,
      }))
    : []
  saving.value = true
  try {
    await datasetApi.replaceRows(props.datasetId, [...existing, ...imported])
    ElMessage.success(`已导入 ${imported.length} 个 sheet（共 ${existing.length + imported.length} 个）`)
    emit('imported')
    emit('update:visible', false)
  } catch (e: any) {
    ElMessage.error(e.message || '导入失败')
  } finally {
    saving.value = false
  }
}

watch(() => props.visible, (v) => {
  if (!v) return
  text.value = ''
  parsed.value = null
  parseError.value = ''
  overwrite.value = false
  firstRowIsHeader.value = true
  singleField.value = existingFirstField.value
})
</script>

<style scoped>
.paste-area :deep(textarea) { font-size: 12px; }
.opts-bar { display: flex; align-items: center; gap: 14px; margin: 10px 0 2px; flex-wrap: wrap; }
.opt-label { font-size: 13px; color: var(--el-text-color-secondary); }
.parse-bar { display: flex; align-items: center; gap: 12px; margin: 10px 0; }
.stat { font-size: 13px; color: var(--el-text-color-secondary); }
.stat.err { color: var(--el-color-danger); }
.mono { font-family: 'JetBrains Mono', Consolas, monospace; }
</style>
