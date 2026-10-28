<template>
  <div class="page">
    <div class="page-head">
      <div class="head-left">
        <span class="page-title">动作库</span>
        <el-button type="primary" @click="openCreate">+ 新建 JS 模板动作</el-button>
      </div>
      <div class="head-right">
        <el-input
          v-model="keyword"
          style="width: 260px"
          placeholder="搜索动作 / key / 描述 / 参数"
          clearable
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
    </div>

    <div class="body">
      <el-card shadow="never" class="card">
        <div class="table-tip">
          原生 {{ nativeCount }} · 封装 {{ builtinCount }} · JS 模板 {{ list.length }} · 全量 {{ nativeCount + builtinCount + list.length }}；
          展开行看参数与用法，封装动作可覆写描述，JS 模板项目级增删改；词表口径与帮助「UI 动作解析」一致
        </div>
        <el-table :data="filteredRows" size="small" row-key="key" height="100%">
          <template #empty>
            <EmptyState description="没有匹配的动作" :image-size="70" />
          </template>
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-body">
                <div class="expand-row">
                  <span class="expand-label">描述</span>
                  <span class="expand-desc">{{ row.desc || '—' }}</span>
                </div>
                <template v-if="row.params?.length">
                  <div class="expand-label">参数</div>
                  <el-table :data="row.params" size="small" border class="param-table">
                    <el-table-column prop="name" label="参数" width="130">
                      <template #default="{ row: p }"><span class="mono">{{ p.name }}</span></template>
                    </el-table-column>
                    <el-table-column label="必填" width="56" align="center">
                      <template #default="{ row: p }">{{ p.required ? '是' : '—' }}</template>
                    </el-table-column>
                    <el-table-column prop="desc" label="说明" min-width="360" />
                  </el-table>
                </template>
                <div v-if="row.origin === 'js' && row.meta" class="expand-row">
                  <span class="expand-label">脚本</span>
                  <pre class="mono script-pre">{{ row.meta.script }}</pre>
                </div>
                <div v-if="row.updater" class="expand-row">
                  <span class="expand-label">{{ row.origin === 'js' ? '维护人' : '覆盖人' }}</span>
                  <span>{{ row.updater }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="动作" min-width="190">
            <template #default="{ row }">
              <div class="cell-name">
                <span class="name">{{ row.name }}</span>
                <span v-if="row.overridden" class="flag" title="描述已项目级覆盖">覆</span>
                <span class="mono key">{{ row.key }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="originTag(row.origin)">{{ originLabel(row.origin) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="desc" label="描述" min-width="340" show-overflow-tooltip>
            <template #default="{ row }">{{ row.desc || '—' }}</template>
          </el-table-column>
          <el-table-column label="参数" width="64" align="center">
            <template #default="{ row }">{{ row.params?.length || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <template v-if="row.origin === 'js'">
                <el-button link type="primary" size="small" @click="openEditJs(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="onRemove(row.meta!)">删除</el-button>
              </template>
              <el-button v-else-if="row.origin === 'builtin'" link type="primary" size="small" @click="openDesc(row)">
                覆写描述
              </el-button>
              <span v-else class="op-none">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- 编辑抽屉：新建/编辑 JS 模板 · 封装动作描述覆盖 -->
    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="min(720px, 92vw)" :close-on-click-modal="false">
      <el-form v-if="drawerMode === 'create' || drawerMode === 'editJs'" label-width="80px">
        <el-form-item label="动作名" required>
          <el-input v-model="form.name" placeholder="如 校验合计金额（同项目唯一）" style="max-width: 360px" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="何时用 / 入参 args 怎么传 / 返回什么（多行）——展示在编排下拉与帮助中心，给团队看"
          />
        </el-form-item>
        <el-form-item label="脚本" required>
          <JsCodeEditor v-model="form.script" :height="360" />
          <p class="form-tip">JS 函数体：入参 args（步骤传参），页面上下文可访问 document/window；return 值进 facts.result</p>
        </el-form-item>
      </el-form>
      <div v-else-if="drawerMode === 'desc' && selectedRow">
        <div class="edit-tip">执行逻辑内置不可改；描述为项目级覆盖（空 = 默认文案），编排下拉与帮助中心同步生效</div>
        <div class="builtin-desc">默认描述：{{ selectedRow.builtinDesc }}</div>
        <el-input
          v-model="descForm.text"
          type="textarea"
          :rows="5"
          placeholder="修改后的动作描述，留空保存 = 恢复默认描述"
        />
      </div>

      <template #footer>
        <template v-if="drawerMode === 'create' || drawerMode === 'editJs'">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
        </template>
        <template v-else-if="drawerMode === 'desc'">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button :loading="saving" @click="onDescSave(false)">恢复默认</el-button>
          <el-button type="primary" :loading="saving" @click="onDescSave(true)">保存描述</el-button>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
/**
 * 动作库（表格 + 抽屉）：全量动作一页可检索（原生 + 封装 + JS 模板），
 * 展开行看参数表，编辑/覆写走右侧抽屉。
 * - 原生：引擎内置只读（词表 utils/ui.ts）
 * - 封装：描述项目级覆盖（ui-action-docs），覆盖后编排下拉/帮助中心同步显示
 * - JS 模板：项目级增删改（custom-actions），CodeMirror 语法高亮编辑
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { customActionApi, uiActionDocApi, type CustomAction, type UiActionDoc } from '@/api'
import { UI_ACTIONS, type UiActionMeta, type UiActionParam } from '@/utils/ui'
import { useAppStore } from '@/stores'
import EmptyState from '@/components/EmptyState.vue'
import JsCodeEditor from '@/components/JsCodeEditor.vue'

const store = useAppStore()

type RowOrigin = 'native' | 'builtin' | 'js'
interface Row {
  key: string
  name: string
  desc: string
  builtinDesc?: string
  overridden?: boolean
  origin: RowOrigin
  params?: UiActionParam[]
  updater?: string | null
  meta?: CustomAction
}

const list = ref<CustomAction[]>([])
const docs = ref<UiActionDoc[]>([])
const loading = ref(false)
const keyword = ref('')

function docOf(actionKey: string): UiActionDoc | undefined {
  return docs.value.find((d) => d.action_key === actionKey)
}

/** 原生词表 / 内置封装（custom 为步骤占位，模板清单在 JS 模板中管理） */
const nativeActions = computed<UiActionMeta[]>(() => UI_ACTIONS.filter((a) => a.origin === 'native'))
const builtinActions = computed<UiActionMeta[]>(() =>
  UI_ACTIONS.filter((a) => a.origin === 'wrapped' && a.action !== 'custom'))
const nativeCount = computed(() => nativeActions.value.length)
const builtinCount = computed(() => builtinActions.value.length)

/** 全量行：原生 → 封装 → JS 模板（词表序 + 库序） */
const rows = computed<Row[]>(() => [
  ...nativeActions.value.map((a) => ({ key: a.action, name: a.name, desc: a.desc, origin: 'native' as const, params: a.params })),
  ...builtinActions.value.map((a) => {
    const doc = docOf(a.action)
    return {
      key: a.action, name: a.name,
      desc: doc?.usage_text || a.desc,
      builtinDesc: a.desc, overridden: !!doc,
      origin: 'builtin' as const, params: a.params, updater: doc?.updated_by_name,
    }
  }),
  ...list.value.map((ca) => ({
    key: `custom:${ca.id}`, name: ca.name, desc: ca.description || '',
    origin: 'js' as const, updater: ca.updated_by_name, meta: ca,
  })),
])

const filteredRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return rows.value
  return rows.value.filter((r) =>
    [r.name, r.key, r.desc, r.params?.map((p) => `${p.name}${p.desc}`).join('') || '', r.meta?.script || '']
      .join(' ').toLowerCase().includes(kw))
})

function originLabel(o: RowOrigin) {
  return o === 'native' ? '原生' : o === 'builtin' ? '封装' : 'JS'
}
function originTag(o: RowOrigin) {
  return o === 'native' ? 'info' : o === 'builtin' ? 'warning' : 'success'
}

// ---- 抽屉编辑态 ----
const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'editJs' | 'desc'>('create')
const selectedRow = ref<Row | null>(null)
const form = ref({ name: '', description: '', script: '' })
const descForm = ref({ text: '' })
const saving = ref(false)

const drawerTitle = computed(() =>
  drawerMode.value === 'create' ? '新建 JS 模板动作'
    : drawerMode.value === 'editJs' ? `编辑 JS 模板 · custom:${selectedRow.value?.meta?.id ?? ''}`
      : `覆写描述 · ${selectedRow.value?.name ?? ''}`)

function openCreate() {
  drawerMode.value = 'create'
  selectedRow.value = null
  form.value = { name: '', description: '', script: '' }
  drawerVisible.value = true
}

function openEditJs(row: Row) {
  if (!row.meta) return
  drawerMode.value = 'editJs'
  selectedRow.value = row
  form.value = { name: row.meta.name, description: row.meta.description || '', script: row.meta.script }
  drawerVisible.value = true
}

function openDesc(row: Row) {
  drawerMode.value = 'desc'
  selectedRow.value = row
  descForm.value.text = docOf(row.key)?.usage_text || ''
  drawerVisible.value = true
}

async function load() {
  if (!store.currentProjectId) return
  loading.value = true
  try {
    const [actions, docList] = await Promise.all([
      customActionApi.list(store.currentProjectId),
      uiActionDocApi.list(store.currentProjectId),
    ])
    list.value = actions
    docs.value = docList
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// keep-alive 下切换项目：关抽屉防旧项目数据残留，重新加载（对齐 ElementLibrary/EnvManage 惯例）
watch(() => store.currentProjectId, (n, old) => {
  if (n !== old) {
    drawerVisible.value = false
    keyword.value = ''
    load()
  }
})

// ---- 封装动作：描述覆盖 ----
async function onDescSave(keep: boolean) {
  const row = selectedRow.value
  if (!row || !store.currentProjectId) return
  const text = keep ? descForm.value.text.trim() : ''
  if (keep && !text) {
    ElMessage.warning('描述为空；如需恢复默认请点「恢复默认」')
    return
  }
  saving.value = true
  try {
    await uiActionDocApi.upsert(store.currentProjectId, row.key, text)
    ElMessage.success(text ? '描述已更新，编排下拉与帮助中心同步生效' : '已恢复默认描述')
    drawerVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ---- JS 模板动作 ----
async function onSave() {
  if (!form.value.name.trim() || !form.value.script.trim()) {
    ElMessage.warning('动作名和脚本不能为空')
    return
  }
  if (!store.currentProjectId) return
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      description: form.value.description.trim() || undefined,
      script: form.value.script,
    }
    if (drawerMode.value === 'create') {
      await customActionApi.create({ project_id: store.currentProjectId, ...payload })
      ElMessage.success('已创建，编排时在「自定义动作」步骤中选用')
    } else if (selectedRow.value?.meta) {
      await customActionApi.update(selectedRow.value.meta.id, payload)
      ElMessage.success('已更新')
    }
    drawerVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onRemove(row: CustomAction) {
  try {
    await ElMessageBox.confirm(
      `确认删除自定义动作「${row.name}」？引用它的节点执行时会报错提示重新选择`,
      '删除自定义动作',
      { type: 'warning', confirmButtonText: '删除' },
    )
  } catch {
    return
  }
  try {
    await customActionApi.remove(row.id)
    ElMessage.success('已删除')
    drawerVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.body {
  flex: 1;
  min-height: 0;
  display: flex;
}
.card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 14px;
}
.table-tip {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-bottom: 10px;
}
.cell-name {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}
.cell-name .name {
  font-weight: 500;
}
.cell-name .key {
  font-size: 11px;
  color: var(--app-text-muted);
}
.flag {
  flex: none;
  font-size: 11px;
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 3px;
  padding: 0 3px;
}
.op-none {
  color: var(--app-text-muted);
}
.expand-body {
  padding: 4px 12px 8px 48px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.expand-row {
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.expand-label {
  flex: none;
  font-size: 12px;
  color: var(--app-text-muted);
}
.expand-desc {
  font-size: 13px;
  line-height: 1.7;
}
.param-table {
  max-width: 760px;
}
.script-pre {
  margin: 0;
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  flex: 1;
  min-width: 0;
}
.edit-tip {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-bottom: 10px;
}
.builtin-desc {
  font-size: 13px;
  color: var(--app-text-muted);
  line-height: 1.7;
  margin-bottom: 10px;
}
.form-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
