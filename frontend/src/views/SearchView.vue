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
        <label class="debug-toggle">
          <input type="checkbox" :checked="debugEnabled" :disabled="debugBusy" @change="onDebugToggle" />
          Debug
        </label>
      </div>
      <p class="hint">Top-1 最大化展示；其余按相似度列在下方。默认 Top-K 可在设置修改。</p>

      <div v-if="debugEnabled" class="debug-panel">
        <div class="row">
          <label>
            N 噪声向量
            <input v-model.number="debugN" type="number" min="1" max="5000" />
          </label>
          <label>
            M 探针数
            <input v-model.number="debugM" type="number" min="1" max="500" />
          </label>
          <button class="secondary" :disabled="debugBusy" @click="applyNoiseN">应用 N</button>
          <button :disabled="debugBusy || busy" @click="runBenchmark">跑基准</button>
        </div>
        <p class="debug-metrics">
          索引 {{ debugStatus.ntotal ?? '-' }} 条 · 噪声 {{ debugStatus.n ?? 0 }} · dim {{ debugStatus.dim ?? '-' }}
          <span v-if="lastElapsed != null"> · 最近检索 {{ lastElapsed }} ms</span>
        </p>
        <p v-if="benchmark" class="debug-metrics">
          基准：probed {{ benchmark.probed }} · hit@{{ benchmark.k }} =
          {{ (benchmark.hit_at_k * 100).toFixed(1) }}%
          · 均值 {{ benchmark.elapsed_ms_mean }} ms
          · 中位 {{ benchmark.elapsed_ms_median }} ms
          · min/max {{ benchmark.elapsed_ms_min }}/{{ benchmark.elapsed_ms_max }} ms
        </p>
      </div>

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
import { onMounted, ref } from 'vue'
import { api } from '../api'

const q = ref('')
const busy = ref(false)
const err = ref('')
const top1 = ref(null)
const others = ref([])
const lastElapsed = ref(null)

const debugEnabled = ref(false)
const debugBusy = ref(false)
const debugN = ref(100)
const debugM = ref(20)
const debugStatus = ref({})
const benchmark = ref(null)

async function refreshDebugStatus() {
  debugStatus.value = await api('/api/search/debug/status')
  debugEnabled.value = !!debugStatus.value.enabled
  if (!debugN.value) debugN.value = debugStatus.value.default_n || 100
  if (!debugM.value) debugM.value = debugStatus.value.default_m || 20
}

async function onDebugToggle(ev) {
  const want = ev.target.checked
  debugBusy.value = true
  err.value = ''
  try {
    if (want) {
      const n = Math.min(5000, Math.max(1, Number(debugN.value) || 100))
      debugN.value = n
      debugStatus.value = await api('/api/search/debug/enable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n }),
      })
      debugEnabled.value = true
      benchmark.value = null
    } else {
      debugStatus.value = await api('/api/search/debug/disable', { method: 'POST' })
      debugEnabled.value = false
      benchmark.value = null
    }
    await refreshDebugStatus()
  } catch (e) {
    err.value = String(e.message || e)
    ev.target.checked = debugEnabled.value
  } finally {
    debugBusy.value = false
  }
}

async function applyNoiseN() {
  if (!debugEnabled.value) return
  debugBusy.value = true
  err.value = ''
  try {
    const n = Math.min(5000, Math.max(1, Number(debugN.value) || 100))
    debugN.value = n
    debugStatus.value = await api('/api/search/debug/enable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n }),
    })
    benchmark.value = null
    await refreshDebugStatus()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    debugBusy.value = false
  }
}

async function runBenchmark() {
  debugBusy.value = true
  err.value = ''
  try {
    const m = Math.max(1, Number(debugM.value) || 20)
    debugM.value = m
    benchmark.value = await api('/api/search/debug/benchmark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ m }),
    })
    await refreshDebugStatus()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    debugBusy.value = false
  }
}

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
    lastElapsed.value = data.elapsed_ms ?? null
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
    lastElapsed.value = data.elapsed_ms ?? null
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
    ev.target.value = ''
  }
}

onMounted(async () => {
  try {
    await refreshDebugStatus()
  } catch {
    /* ignore */
  }
})
</script>

<style scoped>
.search-box { margin-bottom: 1rem; }
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: end; }
.row input { min-width: 280px; flex: 1; }
.debug-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--muted);
  font-size: 0.9rem;
  user-select: none;
}
.debug-panel {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}
.debug-panel input[type='number'] {
  width: 100px;
  min-width: 100px;
  flex: 0;
  display: block;
  margin-top: 0.25rem;
}
.debug-metrics { color: var(--muted); font-size: 0.85rem; margin: 0.35rem 0 0; }
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
