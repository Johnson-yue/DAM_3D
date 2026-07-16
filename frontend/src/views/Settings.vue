<template>
  <div class="card">
    <h2>设置</h2>
    <p class="hint">API Key 仅保存在本地 config.local.json，不会写入源码。</p>
    <form class="form" @submit.prevent="save">
      <label>托管库根目录 <input v-model="form.library_root" /></label>
      <label>Blender 路径 <input v-model="form.blender_exe" /></label>
      <label>SigLIP 权重路径 <input v-model="form.siglip_path" /></label>
      <label>
        OpenRouter API Key
        <input v-model="form.openrouter_api_key" type="password" :placeholder="keyPlaceholder" />
      </label>
      <label>打标模型 <input v-model="form.openrouter_model" /></label>
      <label class="check"><input v-model="form.auto_tag_enabled" type="checkbox" /> 启用自动打标</label>
      <label>打标 Prompt <textarea v-model="form.auto_tag_prompt" rows="2" /></label>
      <label>Top-K <input v-model.number="form.top_k" type="number" min="1" max="50" /></label>
      <label>多视图数量 <input v-model.number="form.view_count" type="number" min="1" max="8" /></label>
      <label>α 视觉权重 <input v-model.number="form.search_alpha" type="number" step="0.05" min="0" max="1" /></label>
      <label>β 标签权重 <input v-model.number="form.search_beta" type="number" step="0.05" min="0" max="1" /></label>
      <button type="submit" :disabled="busy">保存</button>
    </form>
    <pre class="status">{{ statusText }}</pre>
    <p v-if="msg" class="msg">{{ msg }}</p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const form = ref({
  library_root: '',
  blender_exe: '',
  siglip_path: '',
  openrouter_api_key: '',
  openrouter_model: '',
  auto_tag_enabled: true,
  auto_tag_prompt: '',
  top_k: 10,
  view_count: 4,
  search_alpha: 0.7,
  search_beta: 0.3,
})
const keyPlaceholder = ref('未设置')
const busy = ref(false)
const msg = ref('')
const statusText = ref('')

onMounted(async () => {
  const s = await api('/api/settings')
  form.value = {
    ...form.value,
    ...s,
    openrouter_api_key: '',
  }
  keyPlaceholder.value = s.openrouter_api_key_set ? '已设置（留空则保持不变）' : '未设置'
  const st = await api('/api/settings/status')
  statusText.value = JSON.stringify(st, null, 2)
})

async function save() {
  busy.value = true
  msg.value = ''
  try {
    const body = { ...form.value }
    if (!body.openrouter_api_key) delete body.openrouter_api_key
    await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    msg.value = '已保存'
    const st = await api('/api/settings/status')
    statusText.value = JSON.stringify(st, null, 2)
  } catch (e) {
    msg.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.form { display: grid; gap: 0.75rem; max-width: 720px; }
label { display: grid; gap: 0.35rem; }
.check { display: flex; align-items: center; gap: 0.5rem; }
.hint, .msg { color: var(--muted); }
.status {
  margin-top: 1rem; background: #0b1016; padding: 0.75rem; border-radius: 8px;
  overflow: auto; font-size: 0.85rem;
}
</style>
