<template>
  <div ref="hostEl" class="js-code-editor" :style="{ height: `${height}px` }"></div>
</template>

<script setup lang="ts">
/** CodeMirror 6 轻封装：JS 语法高亮 + 行号，v-model 双向同步（动作库 JS 模板编辑用）。
 *  外部赋值仅在内容不同时重置文档，避免输入过程中光标被拉回行首。 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorView, basicSetup } from 'codemirror'
import { javascript } from '@codemirror/lang-javascript'

const props = withDefaults(defineProps<{ modelValue: string; height?: number }>(), { height: 320 })
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const hostEl = ref<HTMLElement>()
let view: EditorView | undefined

onMounted(() => {
  view = new EditorView({
    doc: props.modelValue,
    extensions: [
      basicSetup,
      javascript(),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) emit('update:modelValue', u.state.doc.toString())
      }),
      EditorView.theme({
        '&': { height: '100%', fontSize: '12.5px' },
        '.cm-scroller': { fontFamily: 'var(--app-font-mono)' },
      }),
    ],
    parent: hostEl.value,
  })
})

watch(() => props.modelValue, (v) => {
  if (view && v !== view.state.doc.toString()) {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } })
  }
})

onBeforeUnmount(() => view?.destroy())
</script>

<style scoped>
.js-code-editor {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
}
.js-code-editor :deep(.cm-editor) {
  background: var(--el-fill-color-blank);
}
.js-code-editor :deep(.cm-gutters) {
  background: var(--el-fill-color-light);
  color: var(--app-text-muted);
}
</style>
