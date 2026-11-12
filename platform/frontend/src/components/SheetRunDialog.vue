<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { caseApi, type DataSetSheetOut, type SheetSelectionIn, type TestCase } from '@/api'

/**
 * 用例执行「按 sheet 选择」弹窗：哪几个数据集的哪几个 sheet 各跑一条记录。
 * 打开缺省 = bound 数据集全 sheet 勾满（与直接执行等价），未 bound 数据集
 * 不勾（也可临时勾选执行）；确认后 emit('confirm', selection) 并自关，
 * 发射由父视图完成。临时生效，不改用例绑定与数据集内容。
 */
const props = defineProps<{
  modelValue: boolean
  /** 目标用例（需 id/name/bound_dataset_ids） */
  caseItem: TestCase | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', selection: SheetSelectionIn[]): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

interface CaseDataset { id: number; name: string; rows: DataSetSheetOut[] }
const datasets = ref<CaseDataset[]>([])
const loading = ref(false)
const loadError = ref('')
/** 勾选键 `${dataset_id}:${row_index}`（el-checkbox-group 值数组） */
const checked = ref<string[]>([])

const boundIds = computed(() => new Set(props.caseItem?.bound_dataset_ids || []))

async function loadDatasets() {
  if (!props.caseItem) { datasets.value = []; return }
  loading.value = true
  loadError.value = ''
  try {
    datasets.value = await caseApi.datasets(props.caseItem.id)
  } catch (e: any) {
    loadError.value = e?.message || '加载数据集失败'
    datasets.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (open) => {
  if (!open) return
  loadDatasets().then(() => {
    // 缺省勾满 bound 数据集的全部 sheet（与「直接执行」等价；未 bound 不勾）
    checked.value = datasets.value
      .filter((d) => boundIds.value.has(d.id))
      .flatMap((d) => d.rows.map((r) => `${d.id}:${r.row_index}`))
  })
})

const keysOf = (d: CaseDataset) => d.rows.map((r) => `${d.id}:${r.row_index}`)
const groupChecked = (d: CaseDataset) => keysOf(d).filter((k) => checked.value.includes(k))
const allInGroup = (d: CaseDataset) => groupChecked(d).length === d.rows.length
const someInGroup = (d: CaseDataset) => groupChecked(d).length > 0 && !allInGroup(d)

function toggleGroup(d: CaseDataset, on: boolean) {
  const keys = keysOf(d)
  const rest = checked.value.filter((k) => !keys.includes(k))
  checked.value = on ? [...rest, ...keys] : rest
}

/** 选中数（去重防御：数据集行序重排后的悬空键不算） */
const pickedCount = computed(() =>
  datasets.value.reduce((n, d) => n + groupChecked(d).length, 0))

function preview(r: DataSetSheetOut): string {
  const vals = Object.entries(r.data || {})
    .filter(([k]) => k !== 'nodes')
    .slice(0, 3)
    .map(([, v]) => String(v))
  const text = vals.join(' · ')
  return text.length > 42 ? text.slice(0, 42) + '…' : text
}

function confirm() {
  const selection: SheetSelectionIn[] = []
  for (const d of datasets.value) {
    const idxs = groupChecked(d)
      .map((k) => Number(k.split(':')[1]))
      .sort((a, b) => a - b)
    if (idxs.length) selection.push({ dataset_id: d.id, row_indexes: idxs })
  }
  if (!selection.length) return
  emit('confirm', selection)
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="按 sheet 选择执行"
    width="min(680px, 92vw)"
    align-center
    :close-on-click-modal="false"
  >
    <div class="sr-bar">
      <span class="sr-case">{{ caseItem?.name }}</span>
      <span class="sr-hint">勾选的 sheet 各跑一条记录 · 临时生效不改绑定</span>
    </div>

    <div v-loading="loading" class="sr-body">
      <div v-if="loadError" class="app-load-error">
        <span>{{ loadError }}</span>
        <el-button size="small" @click="loadDatasets">重试</el-button>
      </div>
      <template v-else>
        <div class="sr-list">
          <template v-for="d in datasets" :key="d.id">
            <div class="sr-group">
              <el-checkbox
                :model-value="d.rows.length ? allInGroup(d) : false"
                :indeterminate="someInGroup(d)"
                :disabled="!d.rows.length"
                @change="(v: any) => toggleGroup(d, !!v)"
              >
                {{ d.name }}
              </el-checkbox>
              <el-tag v-if="boundIds.has(d.id)" size="small" effect="plain" type="info">绑定</el-tag>
              <span class="sr-group-count">{{ d.rows.length ? `${groupChecked(d).length}/${d.rows.length}` : '无 sheet' }}</span>
            </div>
            <el-checkbox-group :model-value="checked" @update:model-value="(v: any) => (checked = v)">
              <el-checkbox
                v-for="r in d.rows"
                :key="`${d.id}:${r.row_index}`"
                :value="`${d.id}:${r.row_index}`"
                class="sr-sheet"
              >
                <span class="sr-sheet-name" :title="r.label">{{ r.label }}</span>
                <span class="sr-sheet-preview">{{ preview(r) }}</span>
              </el-checkbox>
            </el-checkbox-group>
          </template>
        </div>
        <div v-if="!datasets.length" class="sr-empty">该用例暂无数据集</div>
      </template>
    </div>

    <template #footer>
      <span class="sr-count">已选 {{ pickedCount }} 套</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!pickedCount" @click="confirm">
        执行所选{{ pickedCount ? ` ${pickedCount} 套` : '' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.sr-bar {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.sr-case {
  font-weight: 600;
}
.sr-hint {
  font-size: 12px;
  color: var(--app-text-muted);
}
.sr-body {
  min-height: 220px;
}
.sr-list {
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 4px 12px;
}
.sr-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0 2px;
}
.sr-group-count {
  font-size: 12px;
  color: var(--app-text-faint);
}
.sr-sheet {
  width: 100%;
  height: 30px;
  margin-left: 22px;
}
.sr-sheet-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  display: inline-block;
}
.sr-sheet-preview {
  margin-left: 8px;
  font-size: 12px;
  color: var(--app-text-faint);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  display: inline-block;
}
.sr-empty {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--app-text-faint);
}
.sr-count {
  float: left;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 32px;
}
</style>
