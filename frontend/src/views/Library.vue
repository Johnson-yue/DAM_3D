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
      </div>
      <p class="hint">原件会复制到托管库；预处理异步进行。源文件不会被改写。</p>
      <p v-if="msg" class="msg">{{ msg }}</p>
    </section>

    <section class="grid">
      <article v-for="a in assets" :key="a.id" class="card item">
        <div class="thumb-wrap">
          <img v-if="a.best_view_url" :src="a.best_view_url" :alt="a.name" />
          <div v-else class="placeholder">无预览</div>
        </div>
        <h3>{{ a.name }}</h3>
        <div class="meta">
          <span class="badge" :class="statusClass(a.status)">{{ a.status }}</span>
          <span class="badge">{{ a.ext }}</span>
          <span class="badge">tag: {{ a.tag_status }}</span>
        </div>
        <div class="actions">
          <router-link :to="`/preview/${a.id}`">预览 / 批注</router-link>
          <button class="secondary" @click="reprocess(a.id)">重处理</button>
        </div>
        <p v-if="a.error_message" class="err">{{ a.error_message }}</p>
      </article>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api, statusClass } from '../api'

const assets = ref([])
const scanDir = ref('E:\\code\\Data\\3D\\CC')
const busy = ref(false)
const msg = ref('')
let timer = null

async function refresh() {
  assets.value = await api('/api/assets')
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

async function reprocess(id) {
  await api(`/api/assets/${id}/reprocess`, { method: 'POST' })
  msg.value = `资产 ${id} 已重新入队`
  await refresh()
}

onMounted(async () => {
  await refresh()
  timer = setInterval(refresh, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.toolbar { margin-bottom: 1rem; }
.row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; }
.hint, .msg { color: var(--muted); font-size: 0.9rem; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
}
.item h3 { margin: 0.5rem 0; font-size: 1rem; word-break: break-all; }
.thumb-wrap {
  aspect-ratio: 1; background: #0b1016; border-radius: 8px; overflow: hidden;
  display: grid; place-items: center;
}
.thumb-wrap img { width: 100%; height: 100%; object-fit: contain; }
.placeholder { color: var(--muted); }
.meta { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }
.actions { display: flex; gap: 0.75rem; align-items: center; }
.err { color: var(--err); font-size: 0.8rem; }
.upload input { display: block; margin-top: 0.25rem; }
</style>
