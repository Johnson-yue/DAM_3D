<template>
  <div>
    <section class="card search-box">
      <div class="row">
        <input v-model="q" placeholder="文字检索，例如：船 / 蝴蝶" @keyup.enter="searchText" />
        <button :disabled="busy" @click="searchText">文字检索</button>
        <label class="upload">
          以图搜图
          <input type="file" accept="image/*" @change="searchImage" />
        </label>
      </div>
      <p class="hint">Top-1 最大化展示；其余按相似度列在下方。默认 Top-K 可在设置修改。</p>
      <p v-if="err" class="err">{{ err }}</p>
    </section>

    <section v-if="top1" class="card hero">
      <div class="hero-grid">
        <img :src="top1.best_view_url" :alt="top1.asset.name" />
        <div>
          <div class="rank">Top-1</div>
          <h2>{{ top1.asset.name }}</h2>
          <p>score {{ top1.score.toFixed(4) }} · visual {{ top1.visual_sim.toFixed(4) }} · tag {{ top1.tag_match.toFixed(4) }}</p>
          <p>最佳视角：{{ top1.best_view_id }}</p>
          <div class="tags">
            <span v-for="t in top1.asset.tags" :key="t.id" class="badge">{{ t.tag }}</span>
          </div>
          <router-link :to="`/preview/${top1.asset.id}`">打开预览</router-link>
        </div>
      </div>
    </section>

    <section v-if="others.length" class="list">
      <article v-for="(h, i) in others" :key="h.asset.id" class="card row-item">
        <img :src="h.best_view_url" />
        <div>
          <strong>#{{ i + 2 }} {{ h.asset.name }}</strong>
          <div>score {{ h.score.toFixed(4) }}</div>
          <router-link :to="`/preview/${h.asset.id}`">预览</router-link>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api'

const q = ref('')
const busy = ref(false)
const err = ref('')
const top1 = ref(null)
const others = ref([])

async function searchText() {
  if (!q.value.trim()) return
  busy.value = true
  err.value = ''
  try {
    const fd = new FormData()
    fd.append('q', q.value)
    const data = await api('/api/search/text', { method: 'POST', body: fd })
    top1.value = data.top1
    others.value = data.others || []
    if (!data.top1) err.value = '无结果（可能 Embedding/索引尚未就绪）'
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function searchImage(ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  busy.value = true
  err.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file)
    const data = await api('/api/search/image', { method: 'POST', body: fd })
    top1.value = data.top1
    others.value = data.others || []
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
    ev.target.value = ''
  }
}
</script>

<style scoped>
.search-box { margin-bottom: 1rem; }
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: end; }
.row input { min-width: 280px; flex: 1; }
.hint { color: var(--muted); }
.err { color: var(--err); }
.hero { margin-bottom: 1rem; }
.hero-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 1rem; align-items: center; }
.hero img { width: 100%; max-height: 480px; object-fit: contain; background: #0b1016; border-radius: 8px; }
.rank { color: var(--accent); font-weight: 700; }
.tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.5rem 0; }
.list { display: grid; gap: 0.75rem; }
.row-item { display: grid; grid-template-columns: 120px 1fr; gap: 0.75rem; align-items: center; }
.row-item img { width: 120px; height: 90px; object-fit: contain; background: #0b1016; border-radius: 6px; }
@media (max-width: 800px) {
  .hero-grid { grid-template-columns: 1fr; }
}
</style>
