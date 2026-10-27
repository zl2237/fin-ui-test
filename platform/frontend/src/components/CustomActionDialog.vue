<template>
  <el-dialog
    v-model="visible"
    title="动作库 · 自定义动作"
    width="880px"
    align-center
    :close-on-click-modal="false"
  >
    <div class="ca-intro">
      非原生动作（封装/增强/自定义）统一在此管理：「内置封装」执行逻辑内置、不可删除，<strong>描述可修改</strong>（覆盖默认文案）；
      「JS 模板」为项目级自定义动作，可新建 / 修改 / 删除。全部描述在编排下拉与顶部帮助（? → UI 动作解析）共享给团队。
    </div>

    <div class="ca-toolbar">
      <el-button type="primary" size="small" @click="openCreate">+ 新建 JS 模板动作</el-button>
      <span class="ca-count">共 {{ rows.length }} 个（内置封装 {{ presetActions.length }} + JS 模板 {{ list.length }}）</span>
    </div>

    <el-table v-loading="loading" :data="rows" size="small" stripe max-height="430">
      <template #empty>
        <EmptyState description="暂无动作" :image-size="60" />
      </template>
      <el-table-column label="动作" width="130">
        <template #default="{ row }">
          <span class="mono">{{ row.key }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" width="110" show-overflow-tooltip />
      <el-table-column label="描述（生效）" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          <span :class="{ 'doc-overridden': row.overridden }">{{ row.desc || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="96" align="center">
        <template #default="{ row }">
          <el-tag :type="row.kind === 'builtin' ? 'info' : 'success'" size="small" effect="plain">
            {{ row.kind === 'builtin' ? '内置封装' : 'JS 模板' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="维护人" width="86" align="center">
        <template #default="{ row }">{{ row.updater || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <template v-if="row.kind === 'builtin'">
            <el-tooltip content="编辑描述" placement="top">
              <el-button link type="primary" size="small" :icon="EditPen" @click="openDescEdit(row)" />
            </el-tooltip>
          </template>
          <template v-else>
            <el-tooltip content="编辑" placement="top">
              <el-button link type="primary" size="small" :icon="EditPen" @click="openEdit(row.meta!)" />
            </el-tooltip>
            <el-tooltip content="删除" placement="top">
              <el-button link type="danger" size="small" :icon="Delete" @click="onRemove(row.meta!)" />
            </el-tooltip>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 内置封装动作：描述覆盖编辑（空=恢复默认文案） -->
    <el-dialog v-model="descVisible" :title="`修改描述 · ${descEditing?.key || ''}（${descEditing?.name || ''}）`" width="640px" append-to-body align-center :close-on-click-modal="false">
      <div class="doc-builtin">默认描述：{{ descEditing?.builtinDesc }}</div>
      <el-input
        v-model="descForm.text"
        type="textarea"
        :rows="6"
        placeholder="修改后的动作描述，展示在编排下拉与帮助中心。留空保存 = 恢复默认描述。"
      />
      <p class="form-tip">项目级覆盖；执行逻辑内置不受影响。多行文本，第一行建议一句话概括用途。</p>
      <template #footer>
        <el-button @click="descVisible = false">取消</el-button>
        <el-button :loading="saving" @click="onDescSave(false)">恢复默认</el-button>
        <el-button type="primary" :loading="saving" @click="onDescSave(true)">保存</el-button>
      </template>
    </el-dialog>

    <!-- JS 模板动作 新建/编辑 -->
    <el-dialog v-model="editorVisible" :title="editing ? '编辑 JS 模板动作' : '新建 JS 模板动作'" width="640px" append-to-body align-center :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="动作名" required>
          <el-input v-model="form.name" placeholder="如 校验合计金额（同项目唯一）" />
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
          <el-input v-model="form.script" type="textarea" :rows="8" class="mono" :placeholder="SCRIPT_PLACEHOLDER" />
          <p class="form-tip">
            JS 函数体：入参 args（步骤传参），页面上下文可访问 document/window；return 值进 facts.result
          </p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 动作库 · 自定义动作（非原生动作统一管理）：
 * - 内置封装动作（11 种，执行逻辑内置）：描述项目级覆盖（ui-action-docs），覆盖后编排下拉/帮助中心同步显示
 * - JS 模板动作：项目级模板增删改（custom-actions）
 * 入口在元素库页头；帮助中心「UI 动作解析」实时引用生效描述。
 */
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Delete } from '@element-plus/icons-vue'
import { customActionApi, uiActionDocApi, type CustomAction, type UiActionDoc } from '@/api'
import { UI_ACTIONS, type UiActionMeta } from '@/utils/ui'
import { useAppStore } from '@/stores'
import EmptyState from './EmptyState.vue'

const store = useAppStore()

const visible = defineModel<boolean>({ default: false })

const SCRIPT_PLACEHOLDER = `// 示例：校验费用表合计与明细一致
const rows = [...document.querySelectorAll('tr.fee-row')]
const sum = rows.reduce((a, r) => a + Number(r.dataset.amount || 0), 0)
if (sum !== Number(args.expect)) throw new Error('合计不符: ' + sum)
return 'ok:' + sum`

/** 内置封装动作（非原生词表；custom 为步骤占位，模板清单在 JS 模板中管理） */
const presetActions = computed<UiActionMeta[]>(() =>
  UI_ACTIONS.filter((a) => a.origin === 'wrapped' && a.action !== 'custom'))

interface Row {
  key: string
  name: string
  desc: string
  builtinDesc?: string
  overridden?: boolean
  kind: 'builtin' | 'js'
  updater?: string | null
  meta?: CustomAction
}

const list = ref<CustomAction[]>([])
const docs = ref<UiActionDoc[]>([])
const loading = ref(false)

function docOf(actionKey: string): UiActionDoc | undefined {
  return docs.value.find((d) => d.action_key === actionKey)
}

/** 统一列表：内置封装（描述=项目覆盖||默认）在前，JS 模板在后 */
const rows = computed<Row[]>(() => [
  ...presetActions.value.map((a) => {
    const doc = docOf(a.action)
    return {
      key: a.action, name: a.name,
      desc: doc?.usage_text || a.desc,
      builtinDesc: a.desc, overridden: !!doc,
      kind: 'builtin' as const, updater: doc?.updated_by_name,
    }
  }),
  ...list.value.map((ca) => ({
    key: `custom:${ca.id}`, name: ca.name, desc: ca.description || '',
    kind: 'js' as const, updater: ca.updated_by_name, meta: ca,
  })),
])

// ---- 内置封装：描述覆盖 ----
const descVisible = ref(false)
const descEditing = ref<Row | null>(null)
const descForm = ref({ text: '' })

function openDescEdit(row: Row) {
  descEditing.value = row
  descForm.value.text = docOf(row.key)?.usage_text || ''
  descVisible.value = true
}

async function onDescSave(keep: boolean) {
  if (!descEditing.value || !store.currentProjectId) return
  const text = keep ? descForm.value.text.trim() : ''
  if (keep && !text) {
    ElMessage.warning('描述为空；如需恢复默认请点「恢复默认」')
    return
  }
  saving.value = true
  try {
    await uiActionDocApi.upsert(store.currentProjectId, descEditing.value.key, text)
    ElMessage.success(text ? '描述已更新，编排下拉与帮助中心同步生效' : '已恢复默认描述')
    descVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ---- JS 模板动作 ----
const editorVisible = ref(false)
const editing = ref<CustomAction | null>(null)
const saving = ref(false)
const form = ref({ name: '', description: '', script: '' })

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

watch(visible, (v) => { if (v) load() })

function openCreate() {
  editing.value = null
  form.value = { name: '', description: '', script: '' }
  editorVisible.value = true
}

function openEdit(row: CustomAction) {
  editing.value = row
  form.value = { name: row.name, description: row.description || '', script: row.script }
  editorVisible.value = true
}

async function onSave() {
  if (!form.value.name.trim() || !form.value.script.trim()) {
    ElMessage.warning('动作名和脚本不能为空')
    return
  }
  if (!store.currentProjectId) return
  saving.value = true
  try {
    if (editing.value) {
      await customActionApi.update(editing.value.id, {
        name: form.value.name.trim(),
        description: form.value.description.trim() || undefined,
        script: form.value.script,
      })
      ElMessage.success('已更新')
    } else {
      await customActionApi.create({
        project_id: store.currentProjectId,
        name: form.value.name.trim(),
        description: form.value.description.trim() || undefined,
        script: form.value.script,
      })
      ElMessage.success('已创建，编排时在「自定义动作」步骤中选用')
    }
    editorVisible.value = false
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
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}
</script>

<style scoped>
.ca-intro {
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.7;
  margin-bottom: 10px;
}
.ca-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.ca-count {
  font-size: 12px;
  color: var(--app-text-muted);
}
.doc-overridden {
  color: var(--el-color-primary);
}
.doc-builtin {
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
  margin-bottom: 10px;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.form-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
}
</style>
