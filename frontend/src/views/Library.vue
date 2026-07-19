<template>
  <div>
    <section class="toolbar card">
      <div class="row">
        <label>
          扫描目录
          <input v-model="scanDir" style="min-width: 320px" />
        </label>
        <button :disabled="busy" @click="doScan">扫描入库</button>
        <label class="upload">
          上传文件
          <input type="file" @change="onUpload" />
        </label>
        <button class="secondary" :disabled="busy" @click="refresh">刷新</button>
        <button
          v-if="selectedIds.length"
          class="danger"
          :disabled="busy"
          title="删除选中资产"
          @click="bulkDelete"
        >
          删除选中 ({{ selectedIds.length }})
        </button>
      </div>
      <p class="hint">原件会复制到托管库；预处理异步进行。源文件不会被改写。删除为硬删除，不可恢复。</p>
      <p v-if="msg" class="msg">{{ msg }}</p>
    </section>

    <section class="grid">
      <article v-for="a in assets" :key="a.id" class="card item" :class="{ selected: isSelected(a.id) }">
        <div class="thumb-box">
          <label class="check" @click.stop>
            <input type="checkbox" :checked="isSelected(a.id)" @change="toggleSelect(a.id, $event)" />
          </label>
          <button
            type="button"
            class="delete-icon"
            title="删除此资产"
            @click.stop="deleteOne(a)"
          >
            ⌫
          </button>
          <button
            type="button"
            class="thumb-wrap"
            :title="`打开预览：${a.name}`"
            @click="openPreview(a.id)"
          >
            <img v-if="a.best_view_url" :src="a.best_view_url" :alt="a.name" />
            <div v-else class="placeholder">无预览</div>
          </button>
        </div>
        <h3>{{ a.name }}</h3>
        <div class="meta">
          <span class="badge" :class="statusClass(a.status)">{{ a.status }}</span>
          <span class="badge">{{ a.ext }}</span>
          <span class="badge">tag: {{ a.tag_status }}</span>
        </div>
        <div class="tag-row" @click.stop>
          <template v-if="(a.tags || []).length">
            <span
              v-for="t in visibleTags(a)"
              :key="t.id"
              class="tag-chip"
              :class="{ editing: isEditing(a.id, t.id) }"
            >
              <input
                v-if="isEditing(a.id, t.id)"
                ref="editInput"
                v-model="editDraft"
                class="tag-input"
                @keydown.enter.prevent="commitEdit(a, t)"
                @keydown.esc.prevent="cancelEdit"
                @blur="commitEdit(a, t)"
              />
              <button
                v-else
                type="button"
                class="tag-text"
                title="点击修改标签"
                @click="startEdit(a, t)"
              >
                {{ t.tag }}
              </button>
              <button
                type="button"
                class="tag-del"
                title="删除标签"
                @mousedown.prevent
                @click="removeTag(a, t)"
              >
                ×
              </button>
            </span>
          </template>
          <span v-else class="tag-empty">无标签</span>
        </div>
        <p v-if="a.error_message" class="err">{{ a.error_message }}</p>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, statusClass } from '../api'
import {
  clearSelected,
  getSelectedIds,
  pruneSelected,
  removeSelected,
  setSelected,
} from '../selectionStore'

const router = useRouter()
const assets = ref([])
const scanDir = ref('E:\\code\\Data\\3D\\CC')
const busy = ref(false)
const msg = ref('')
const editing = ref(null)
const editDraft = ref('')
const editInput = ref(null)
// 本地 Set 仅用于触发 Vue 渲染；真实来源是 selectionStore（SPA 导航不丢）。
const selected = ref(new Set(getSelectedIds()))
let timer = null

const selectedIds = computed(() => [...selected.value])

function syncSelectedFromStore() {
  selected.value = new Set(getSelectedIds())
}

function isSelected(id) {
  return selected.value.has(id)
}

function toggleSelect(id, ev) {
  setSelected(id, !!ev.target.checked)
  syncSelectedFromStore()
}

function visibleTags(asset) {
  return (asset.tags || []).slice(0, 3)
}

function isEditing(assetId, tagId) {
  return editing.value?.assetId === assetId && editing.value?.tagId === tagId
}

function openPreview(id) {
  router.push(`/preview/${id}`)
}

async function refresh() {
  // 编辑标签时跳过轮询，避免打断输入框。
  if (editing.value) return
  assets.value = await api('/api/assets')
  pruneSelected(assets.value.map((a) => a.id))
  syncSelectedFromStore()
}

async function persistTags(asset, nextTags) {
  const updated = await api(`/api/assets/${asset.id}/tags`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags: nextTags }),
  })
  const idx = assets.value.findIndex((row) => row.id === asset.id)
  if (idx >= 0) assets.value[idx] = updated
  return updated
}

async function startEdit(asset, tag) {
  editing.value = { assetId: asset.id, tagId: tag.id }
  editDraft.value = tag.tag
  await nextTick()
  const el = Array.isArray(editInput.value) ? editInput.value[0] : editInput.value
  el?.focus?.()
  el?.select?.()
}

function cancelEdit() {
  editing.value = null
  editDraft.value = ''
}

async function commitEdit(asset, tag) {
  if (!isEditing(asset.id, tag.id)) return
  const next = editDraft.value.trim()
  editing.value = null
  if (!next || next === tag.tag) {
    editDraft.value = ''
    return
  }
  const nextTags = (asset.tags || []).map((row) => (row.id === tag.id ? next : row.tag))
  try {
    await persistTags(asset, nextTags)
    msg.value = `已更新标签：${next}`
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    editDraft.value = ''
  }
}

async function removeTag(asset, tag) {
  cancelEdit()
  const nextTags = (asset.tags || []).filter((row) => row.id !== tag.id).map((row) => row.tag)
  try {
    await persistTags(asset, nextTags)
    msg.value = `已删除标签：${tag.tag}`
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function deleteOne(asset) {
  const ok = window.confirm(
    `确认硬删除资产「${asset.name}」？\n将删除托管库原件副本、预览、批注与向量，不可恢复。\n（源盘文件不受影响）`,
  )
  if (!ok) return
  busy.value = true
  try {
    await api(`/api/assets/${asset.id}`, { method: 'DELETE' })
    removeSelected(asset.id)
    syncSelectedFromStore()
    msg.value = `已删除：${asset.name}`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function bulkDelete() {
  const ids = selectedIds.value
  if (!ids.length) return
  const ok = window.confirm(
    `确认硬删除选中的 ${ids.length} 个资产？\n将删除托管库原件副本、预览、批注与向量，不可恢复。`,
  )
  if (!ok) return
  busy.value = true
  try {
    const data = await api('/api/assets/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    const failed = data.failed?.length || 0
    msg.value = failed
      ? `已删除 ${data.deleted.length} 个，失败 ${failed} 个`
      : `已删除 ${data.deleted.length} 个资产`
    for (const id of data.deleted || []) removeSelected(id)
    if (!failed) clearSelected()
    syncSelectedFromStore()
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function doScan() {
  busy.value = true
  msg.value = '扫描中…'
  try {
    const rows = await api('/api/assets/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory: scanDir.value, recursive: true }),
    })
    msg.value = `已导入 / 复用 ${rows.length} 个资产，预处理进行中`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function onUpload(ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  busy.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    await api('/api/assets/upload', { method: 'POST', body: fd })
    msg.value = `已上传 ${file.name}`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    busy.value = false
    ev.target.value = ''
  }
}

onMounted(async () => {
  syncSelectedFromStore()
  await refresh()
  timer = setInterval(refresh, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.toolbar { margin-bottom: 1rem; }
.row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; }
.hint, .msg { color: var(--muted); font-size: 0.9rem; }
.danger {
  background: linear-gradient(180deg, #a33b45, #7a2430);
  border-color: #c45b66;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
}
.item.selected { outline: 1px solid var(--accent); }
.item h3 { margin: 0.5rem 0; font-size: 1rem; word-break: break-all; }
.thumb-box { position: relative; }
.check {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(15, 20, 25, 0.72);
}
.check input { width: 16px; height: 16px; accent-color: var(--accent); }
.delete-icon {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: rgba(15, 20, 25, 0.72);
  color: #f0b4b8;
  font-size: 0.95rem;
  line-height: 1;
  cursor: pointer;
}
.delete-icon:hover {
  background: #3d1e24;
  color: var(--err);
  border-color: #c45b66;
}
.thumb-wrap {
  width: 100%;
  aspect-ratio: 1;
  padding: 0;
  background: #0b1016;
  border: none;
  border-radius: 8px;
  overflow: hidden;
  display: grid;
  place-items: center;
  cursor: pointer;
}
.thumb-wrap:hover { outline: 1px solid var(--accent); }
.thumb-wrap img { width: 100%; height: 100%; object-fit: contain; pointer-events: none; }
.placeholder { color: var(--muted); }
.meta { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  min-height: 1.75rem;
  align-items: center;
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  max-width: 100%;
  padding: 0.1rem 0.2rem 0.1rem 0.45rem;
  border-radius: 999px;
  background: #243040;
  border: 1px solid var(--border);
}
.tag-chip.editing { border-color: var(--accent); }
.tag-text {
  border: none;
  background: transparent;
  padding: 0.1rem 0.15rem;
  color: var(--text);
  font-size: 0.78rem;
  cursor: pointer;
  max-width: 7rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag-input {
  width: 5.5rem;
  padding: 0.1rem 0.25rem;
  font-size: 0.78rem;
  border-radius: 6px;
}
.tag-del {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 0 0.35rem;
  line-height: 1;
  font-size: 0.95rem;
  cursor: pointer;
}
.tag-del:hover { color: var(--err); }
.tag-empty { color: var(--muted); font-size: 0.8rem; }
.err { color: var(--err); font-size: 0.8rem; }
.upload input { display: block; margin-top: 0.25rem; }
</style>
