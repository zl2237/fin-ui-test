<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { caseApi, datasetApi, type TestCase } from '@/api'
import DatasetRowsEditor from '@/components/DatasetRowsEditor.vue'

/**
 * 数据集管理弹窗（用例行内「更多 → 数据集」入口；独立管理页见 DatasetManage.vue）。
 *
 * 左：用例名下数据集列表（1:N 隔离；复制=多场景标准起步；绑定切换走用例更新）。
 * 右：所选数据集的行编辑（DatasetRowsEditor 共用组件）。
 * 任何成功变更 emit('changed')，父视图刷新列表（绑定标记/执行下拉同源）。
 */
const props = defineProps<{
  modelValue: boolean
  caseItem: TestCase | null
  /** 用例当前绑定的数据集 id（绑定中标记；随 changed 后父视图刷新） */
  boundDatasetId?: number | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'changed'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

type DsLite = { id: number; name: string; rows: { row_index: number; data: Record<string, any> }[] }

const loading = ref(false)
const datasets = ref<DsLite[]>([])
const activeId = ref<number | null>(null)

const active = computed(() => datasets.value.find((d) => d.id === activeId.value) || null)
const boundId = computed(() => props.boundDatasetId ?? null)

watch(() => props.modelValue, (open) => {
  if (open && props.caseItem) load()
})

async function load(keepActive?: number) {
  if (!props.caseItem) return
  loading.value = true
  try {
    datasets.value = await caseApi.datasets(props.caseItem.id)
    const want = keepActive ?? activeId.value
    activeId.value = datasets.value.some((d) => d.id === want)
      ? want
      : (datasets.value[0]?.id ?? null)
  } catch (e: any) {
    ElMessage.error(e.message || '数据集加载失败')
  } finally {
    loading.value = false
  }
}

// ===== 数据集级操作 =====
async function createDataset(copyFrom?: number) {
  if (!props.caseItem) return
  let name: string
  try {
    const r = await ElMessageBox.prompt('新数据集名称', copyFrom ? '复制数据集' : '新建数据集', {
      inputValue: copyFrom
        ? (datasets.value.find((d) => d.id === copyFrom)?.name || '') + '-副本'
        : `场景${datasets.value.length + 1}`,
      inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    })
    name = r.value.trim()
  } catch { return }
  try {
    const ds = await datasetApi.create({
      case_id: props.caseItem.id, name,
      copy_from_dataset_id: copyFrom,
    })
    ElMessage.success(`已创建「${ds.name}」${copyFrom ? '（值已拷贝）' : ''}`)
    await load(ds.id)
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function renameDataset() {
  if (!active.value) return
  try {
    const r = await ElMessageBox.prompt('数据集新名称', '改名', {
      inputValue: active.value.name, inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    })
    await datasetApi.update(active.value.id, { name: r.value.trim() })
    await load(active.value.id)
    emit('changed')
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function copyActive() {
  if (!active.value) return
  try {
    const ds = await datasetApi.copy(active.value.id)
    ElMessage.success(`已复制为「${ds.name}」`)
    await load(ds.id)
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e.message || '复制失败')
  }
}

async function removeDataset() {
  if (!active.value || !props.caseItem) return
  try {
    await ElMessageBox.confirm(
      `确认删除数据集「${active.value.name}」（${active.value.rows.length} 行数据一并删除）？`, '删除数据集',
      { type: 'warning' })
  } catch { return }
  try {
    await datasetApi.remove(active.value.id)
    ElMessage.success('已删除')
    await load()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败（被绑定时先解绑）')
  }
}

async function bindDataset(ds: DsLite | null) {
  if (!props.caseItem) return
  try {
    await caseApi.update(props.caseItem.id, { dataset_id: ds?.id ?? null })
    ElMessage.success(ds ? `已绑定「${ds.name}」（执行缺省取第 1 行）` : '已解绑')
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e.message || '绑定失败')
  }
}

/** 行编辑保存完成：重载数据集列表（行数徽标）并通知父视图 */
async function onRowsSaved() {
  await load(activeId.value ?? undefined)
  emit('changed')
}

defineExpose({ load })
</script>

<template>
  <el-dialog v-model="visible" width="min(980px, 96%)" top="6vh"
             :title="`数据集管理 — ${caseItem?.name || ''}`" class="dataset-manage-dialog">
    <div v-loading="loading" class="ds-layout">
      <!-- 左：数据集列表 -->
      <div class="ds-side">
        <div class="ds-side-head">
          <span>数据集（{{ datasets.length }}）</span>
          <el-button size="small" text type="primary" @click="createDataset()">
            <el-icon><Plus /></el-icon>新建
          </el-button>
        </div>
        <div v-for="ds in datasets" :key="ds.id" class="ds-item"
             :class="{ active: ds.id === activeId }" @click="activeId = ds.id">
          <div class="ds-item-main">
            <span class="ds-name" :title="ds.name">{{ ds.name }}</span>
            <el-tag v-if="ds.id === boundId" size="small" type="success" effect="plain">绑定中</el-tag>
          </div>
          <span class="ds-rows">{{ ds.rows.length }} 行</span>
        </div>
        <el-empty v-if="!datasets.length && !loading" description="暂无数据集" :image-size="48" />
        <div class="ds-side-foot">
          <el-button size="small" :disabled="!active" @click="copyActive">复制</el-button>
          <el-button size="small" :disabled="!active" @click="renameDataset">改名</el-button>
          <el-button size="small" type="danger" plain :disabled="!active" @click="removeDataset">删除</el-button>
        </div>
      </div>
      <!-- 右：行编辑（共用组件） -->
      <div class="ds-main">
        <template v-if="active">
          <div class="ds-main-head">
            <span class="ds-main-title">{{ active.name }}</span>
            <el-button v-if="active.id !== boundId" size="small" type="success" plain
                       @click="bindDataset(active!)">设为绑定</el-button>
            <el-button v-else size="small" plain @click="bindDataset(null)">解绑</el-button>
          </div>
          <DatasetRowsEditor :dataset-id="active.id" :rows="active.rows" @saved="onRowsSaved" />
        </template>
        <el-empty v-else-if="!loading" description="选择或新建一个数据集" :image-size="64" />
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.ds-layout {
  display: flex;
  gap: 14px;
  min-height: 420px;
  max-height: calc(88vh - 120px);
}
.ds-side {
  width: 230px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px;
}
.ds-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.ds-item {
  padding: 7px 9px;
  border-radius: 5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.ds-item:hover { background: var(--el-fill-color-light); }
.ds-item.active { background: var(--el-color-primary-light-9); }
.ds-item-main { display: flex; align-items: center; gap: 6px; min-width: 0; }
.ds-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-rows { font-size: 12px; color: var(--el-text-color-secondary); flex-shrink: 0; }
.ds-side-foot {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  gap: 4px;
}
.ds-side-foot .el-button { flex: 1; margin: 0; }
.ds-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.ds-main-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.ds-main-title { font-weight: 600; font-size: 14px; }
@media (max-width: 760px) {
  .ds-layout { flex-direction: column; }
  .ds-side { width: auto; }
}
</style>
