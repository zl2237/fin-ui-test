<template>
  <div class="page">
    <div class="page-head">
      <div class="head-left">
        <span class="page-title">动作库</span>
        <el-button type="primary" @click="openCreate">+ 新建 JS 模板动作</el-button>
      </div>
      <div class="head-right">
        <span class="count-tip">
          共 {{ rows.length }} 个非原生动作（内置封装 {{ presetActions.length }} + JS 模板 {{ list.length }}）；
          另有 {{ nativeCount }} 个原生动作与 1 个自定义动作通道由引擎内置，全量词表 {{ UI_ACTIONS.length + list.length }} 个见帮助「UI 动作解析」
        </span>
      </div>
    </div>

    <div class="body">
      <!-- 左侧：动作列表（内置封装在前，JS 模板在后） -->
      <div class="list-panel">
        <el-scrollbar>
          <div v-for="g in [{ key: 'builtin', label: `内置封装（${presetActions.length}）` }, { key: 'js', label: `JS 模板（${list.length}）` }]"
               :key="g.key" class="list-group">
            <div class="group-title">{{ g.label }}</div>
            <button
              v-for="row in rows.filter((r) => r.kind === g.key)"
              :key="row.key"
              type="button"
              class="list-item"
              :class="{ active: selectedKey === row.key }"
              @click="selectRow(row)"
            >
              <span class="item-main">
                <span class="item-name">{{ row.name }}</span>
                <span class="item-key mono">{{ row.key }}</span>
              </span>
              <span v-if="row.overridden" class="item-flag" title="描述已项目级覆盖">覆</span>
            </button>
          </div>
          <EmptyState v-if="!loading && !rows.length" description="暂无动作，先新建 JS 模板动作" :image-size="60" />
        </el-scrollbar>
      </div>

      <!-- 右侧：编辑区（选中即编辑，无弹窗） -->
      <div class="edit-panel">
        <el-skeleton v-if="loading" :rows="6" animated />

        <!-- 新建 JS 模板 -->
        <template v-else-if="creating">
          <div class="edit-head">
            <span class="edit-title">新建 JS 模板动作</span>
            <span class="edit-tip">保存后编排时在「自定义动作」步骤中选用</span>
          </div>
          <el-form label-width="80px" class="edit-form">
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
          <div class="edit-actions">
            <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
            <el-button @click="cancelEdit">取消</el-button>
          </div>
        </template>

        <!-- 内置封装：只读信息 + 描述覆盖 -->
        <template v-else-if="selected?.kind === 'builtin'">
          <div class="edit-head">
            <span class="edit-title">{{ selected.name }} <span class="mono item-key">{{ selected.key }}</span></span>
            <span class="edit-tip">执行逻辑内置不可改；描述为项目级覆盖（空 = 默认文案），编排下拉与帮助中心同步生效</span>
          </div>
          <div class="builtin-desc">默认描述：{{ selected.builtinDesc }}</div>
          <el-input
            v-model="descForm.text"
            type="textarea"
            :rows="4"
            placeholder="修改后的动作描述，留空保存 = 恢复默认描述"
          />
          <div class="edit-actions">
            <el-button type="primary" :loading="saving" @click="onDescSave(true)">保存描述</el-button>
            <el-button :loading="saving" @click="onDescSave(false)">恢复默认</el-button>
          </div>
        </template>

        <!-- JS 模板：编辑/删除 -->
        <template v-else-if="selected?.kind === 'js' && selected.meta">
          <div class="edit-head">
            <span class="edit-title">编辑 JS 模板动作 <span class="mono item-key">custom:{{ selected.meta.id }}</span></span>
            <span class="edit-tip">维护人 {{ selected.updater || '—' }}；删除后引用它的节点执行时会报错提示重新选择</span>
          </div>
          <el-form label-width="80px" class="edit-form">
            <el-form-item label="动作名" required>
              <el-input v-model="form.name" placeholder="如 校验合计金额（同项目唯一）" style="max-width: 360px" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="3"
                placeholder="何时用 / 入参 args 怎么传 / 返回什么（多行）"
              />
            </el-form-item>
            <el-form-item label="脚本" required>
              <JsCodeEditor v-model="form.script" :height="360" />
              <p class="form-tip">JS 函数体：入参 args（步骤传参），页面上下文可访问 document/window；return 值进 facts.result</p>
            </el-form-item>
          </el-form>
          <div class="edit-actions">
            <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
            <el-button type="danger" plain @click="onRemove(selected.meta)">删除</el-button>
          </div>
        </template>

        <EmptyState v-else description="选择左侧动作查看 / 编辑" :image-size="80" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 动作库（独立页面，自元素库弹窗迁出）：
 * - 内置封装动作：描述项目级覆盖（ui-action-docs），覆盖后编排下拉/帮助中心同步显示
 * - JS 模板动作：项目级模板增删改（custom-actions），CodeMirror 语法高亮编辑
 * 帮助中心「UI 动作解析」实时引用生效描述。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { customActionApi, uiActionDocApi, type CustomAction, type UiActionDoc } from '@/api'
import { UI_ACTIONS, type UiActionMeta } from '@/utils/ui'
import { useAppStore } from '@/stores'
import EmptyState from '@/components/EmptyState.vue'
import JsCodeEditor from '@/components/JsCodeEditor.vue'

const store = useAppStore()

/** 内置封装动作（非原生词表；custom 为步骤占位，模板清单在 JS 模板中管理） */
const presetActions = computed<UiActionMeta[]>(() =>
  UI_ACTIONS.filter((a) => a.origin === 'wrapped' && a.action !== 'custom'))

/** 原生动作数（引擎内置不可配置）——计数行与帮助中心「全量词表」对齐口径用 */
const nativeCount = UI_ACTIONS.filter((a) => a.origin === 'native').length

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

// ---- 选中与编辑态 ----
const selectedKey = ref('')
const selected = computed(() => rows.value.find((r) => r.key === selectedKey.value) || null)
const creating = ref(false)
const descForm = ref({ text: '' })
const form = ref({ name: '', description: '', script: '' })
const saving = ref(false)

function selectRow(row: Row) {
  creating.value = false
  selectedKey.value = row.key
  if (row.kind === 'builtin') {
    descForm.value.text = docOf(row.key)?.usage_text || ''
  } else if (row.meta) {
    form.value = { name: row.meta.name, description: row.meta.description || '', script: row.meta.script }
  }
}

function openCreate() {
  selectedKey.value = ''
  creating.value = true
  form.value = { name: '', description: '', script: '' }
}

function cancelEdit() {
  creating.value = false
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
    // 数据刷新后保持选中项的编辑内容为最新持久化值（未被编辑覆盖的场景）
    if (selected.value) selectRow(selected.value)
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---- 内置封装：描述覆盖 ----
async function onDescSave(keep: boolean) {
  if (!selected.value || !store.currentProjectId) return
  const text = keep ? descForm.value.text.trim() : ''
  if (keep && !text) {
    ElMessage.warning('描述为空；如需恢复默认请点「恢复默认」')
    return
  }
  saving.value = true
  try {
    await uiActionDocApi.upsert(store.currentProjectId, selected.value.key, text)
    ElMessage.success(text ? '描述已更新，编排下拉与帮助中心同步生效' : '已恢复默认描述')
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
    if (creating.value) {
      await customActionApi.create({ project_id: store.currentProjectId, ...payload })
      ElMessage.success('已创建，编排时在「自定义动作」步骤中选用')
      creating.value = false
      await load()
      // 选中新创建的条目（key 由后端 id 决定）
      const created = list.value.find((c) => c.name === payload.name)
      if (created) selectRow({ key: `custom:${created.id}`, name: created.name, desc: '', kind: 'js', updater: '', meta: created })
    } else if (selected.value?.meta) {
      await customActionApi.update(selected.value.meta.id, payload)
      ElMessage.success('已更新')
      await load()
    }
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
    selectedKey.value = ''
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}
</script>

<style scoped>
.count-tip {
  font-size: 12px;
  color: var(--app-text-muted);
}
.body {
  display: flex;
  gap: 12px;
  height: calc(100vh - 148px);
  min-height: 420px;
}
.list-panel {
  width: 300px;
  flex: none;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.list-group {
  padding: 6px 0;
}
.group-title {
  padding: 4px 14px 6px;
  font-size: 12px;
  color: var(--app-text-muted);
}
.list-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 14px;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
}
.list-item:hover {
  background: var(--el-fill-color-light);
}
.list-item.active {
  background: var(--el-color-primary-light-9);
}
.item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-key {
  font-size: 11px;
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-flag {
  flex: none;
  font-size: 11px;
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 3px;
  padding: 0 3px;
}
.edit-panel {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
  padding: 16px 20px;
  overflow: auto;
}
.edit-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.edit-title {
  font-size: 15px;
  font-weight: 600;
}
.edit-tip {
  font-size: 12px;
  color: var(--app-text-muted);
}
.builtin-desc {
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.6;
  margin-bottom: 10px;
}
.edit-form {
  max-width: 900px;
}
.edit-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
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
