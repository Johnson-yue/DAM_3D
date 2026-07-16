<template>
  <div v-if="asset" class="layout">
    <section class="viewer-panel card">
      <div class="toolbar">
        <button class="secondary" :class="{ active: tool==='orbit' }" @click="tool='orbit'">旋转</button>
        <button class="secondary" :class="{ active: materialMode==='clay' }" @click="setMaterialMode('clay')">灰模</button>
        <button class="secondary" :class="{ active: materialMode==='original' }" @click="setMaterialMode('original')">原材质</button>
        <button class="secondary" :class="{ active: tool==='rect' }" @click="tool='rect'">色框</button>
        <button class="secondary" :class="{ active: tool==='arrow' }" @click="tool='arrow'">箭头</button>
        <button class="secondary" :class="{ active: tool==='text' }" @click="tool='text'">文字</button>
        <input type="color" v-model="color" title="颜色" />
        <button @click="saveAnns">保存批注</button>
        <button class="secondary" @click="exportPng">导出 PNG</button>
        <button class="secondary" @click="exportJson">导出 JSON</button>
        <span class="badge">{{ gpuLabel }}</span>
        <span class="badge" :class="statusClass(asset.status)">{{ asset.status }}</span>
      </div>
      <div
        ref="stageRef"
        class="stage"
        @mousedown="onPointerDown"
        @mousemove="onPointerMove"
        @mouseup="onPointerUp"
        @wheel="enterInteractiveView"
        @touchstart="enterInteractiveView"
      >
        <canvas ref="threeRef" class="three"></canvas>
        <!--
          默认首帧与资产库卡片复用同一个 front.png，保证所有格式进入
          预览时的固定画面完全一致；用户旋转/缩放后再切到实时 Three.js。
        -->
        <img
          v-if="showFixedPreview && asset.best_view_url"
          class="fixed-preview"
          :src="asset.best_view_url"
          :alt="`${asset.name} 固定预览`"
        />
        <span v-if="showFixedPreview" class="fixed-preview-hint">拖动或滚轮进入交互 3D</span>
        <canvas ref="annRef" class="ann"></canvas>
      </div>
      <p v-if="loadMsg" class="hint">{{ loadMsg }}</p>
    </section>

    <aside class="side card">
      <h2>{{ asset.name }}</h2>
      <p>格式 {{ asset.ext }} · 打标 {{ asset.tag_status }}</p>
      <label>
        手动标签（逗号分隔）
        <input v-model="tagInput" />
      </label>
      <button class="secondary" @click="saveTags">保存标签</button>
      <button class="secondary" @click="retryAutoTag">重试自动打标</button>
      <div class="tags">
        <span v-for="t in asset.tags" :key="t.id" class="badge">{{ t.tag }} ({{ t.source }})</span>
      </div>
      <p v-if="asset.error_message" class="err">{{ asset.error_message }}</p>
      <router-link to="/">← 返回资产库</router-link>
    </aside>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { api, statusClass } from '../api'

const route = useRoute()
const asset = ref(null)
const tagInput = ref('')
const tool = ref('orbit')
const materialMode = ref('clay')
const showFixedPreview = ref(true)
const color = ref('#ff4d4f')
const gpuLabel = ref('检测 GPU…')
const loadMsg = ref('')
const stageRef = ref(null)
const threeRef = ref(null)
const annRef = ref(null)

let renderer, scene, camera, controls, animationId
let loadedRoot = null
let fallbackLights = []
const originalMaterials = new Map()
let anns = []
let draft = null
let interactiveAt = 0

async function loadAsset() {
  asset.value = await api(`/api/assets/${route.params.id}`)
  // GLB 是浏览器原生交付格式，默认展示其内嵌 PBR 材质、贴图和灯光。
  // 其他格式仍默认灰模，保持既有渲染结果不变。
  materialMode.value = asset.value.ext?.toLowerCase() === '.glb' ? 'original' : 'clay'
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
  const existing = await api(`/api/assets/${route.params.id}/annotations`)
  anns = existing.map((a) => ({ type: a.type, ...a.geometry, color: a.geometry.color || '#ff4d4f' }))
  drawAnns()
}

function detectGPU() {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
    if (!gl) {
      gpuLabel.value = 'CPU/无 WebGL'
      return false
    }
    const dbg = gl.getExtension('WEBGL_debug_renderer_info')
    const rendererInfo = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'WebGL'
    const isSW = /SwiftShader|llvmpipe|Software/i.test(String(rendererInfo))
    gpuLabel.value = isSW ? `软件渲染: ${rendererInfo}` : `GPU: ${rendererInfo}`
    return !isSW
  } catch {
    gpuLabel.value = 'GPU 检测失败'
    return false
  }
}

function initThree() {
  const canvas = threeRef.value
  const stage = stageRef.value
  const w = stage.clientWidth
  const h = stage.clientHeight
  const preferGPU = detectGPU()

  renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: preferGPU ? 'high-performance' : 'low-power',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(w, h, false)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.35
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0b1016)
  camera = new THREE.PerspectiveCamera(50, w / h, 0.01, 2000)
  camera.position.set(1.5, 1.2, 2)
  controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  // 三点布光 + 环境光。灰模不依赖资产原材质，保证任何资产都可看清。
  const ambient = new THREE.AmbientLight(0xffffff, 1.4)
  const hemi = new THREE.HemisphereLight(0xffffff, 0x526070, 2.0)
  const key = new THREE.DirectionalLight(0xffffff, 3.2)
  const fill = new THREE.DirectionalLight(0xb9d8ff, 1.8)
  const rim = new THREE.DirectionalLight(0xffe0bd, 1.5)
  key.position.set(4, 6, 5)
  fill.position.set(-5, 2, 3)
  rim.position.set(1, 3, -5)
  fallbackLights = [ambient, hemi, key, fill, rim]
  scene.add(ambient, hemi, key, fill, rim)

  const annCanvas = annRef.value
  annCanvas.width = w
  annCanvas.height = h

  const t0 = performance.now()
  loadMsg.value = '加载 GLB…'
  const loader = new GLTFLoader()
  loader.load(
    `/api/assets/${route.params.id}/glb`,
    (gltf) => {
      loadedRoot = gltf.scene
      let hasEmbeddedLights = false
      loadedRoot.traverse((obj) => {
        if (obj.isLight) hasEmbeddedLights = true
        if (!obj.isMesh) return
        originalMaterials.set(obj.uuid, obj.material)
        obj.frustumCulled = true
        obj.castShadow = false
        obj.receiveShadow = false
      })
      // GLB 若携带 KHR_lights_punctual，优先使用文件内灯光；
      // 没有内嵌灯光时才启用查看器的兜底三点布光。
      const useEmbeddedLights =
        asset.value.ext?.toLowerCase() === '.glb' && hasEmbeddedLights
      fallbackLights.forEach((light) => {
        light.visible = !useEmbeddedLights
      })
      setMaterialMode(materialMode.value)
      scene.add(loadedRoot)
      const box = new THREE.Box3().setFromObject(loadedRoot)
      const size = box.getSize(new THREE.Vector3())
      const center = box.getCenter(new THREE.Vector3())
      loadedRoot.position.sub(center)
      const maxDim = Math.max(size.x, size.y, size.z) || 1
      // 按相机视场角计算距离，避免大场景过小或局部被裁切。
      const fitHeightDistance = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)))
      const fitWidthDistance = fitHeightDistance / Math.max(camera.aspect, 0.1)
      const distance = 1.35 * Math.max(fitHeightDistance, fitWidthDistance)
      camera.near = Math.max(distance / 1000, 0.001)
      camera.far = Math.max(distance * 100, 1000)
      camera.updateProjectionMatrix()
      camera.position.set(distance * 0.75, distance * 0.5, distance)
      controls.target.set(0, 0, 0)
      controls.minDistance = maxDim * 0.05
      controls.maxDistance = maxDim * 20
      controls.update()
      interactiveAt = performance.now() - t0
      loadMsg.value = `可交互首屏 ${interactiveAt.toFixed(0)} ms（目标 ≤2000ms）`
      controls.enabled = tool.value === 'orbit'
    },
    undefined,
    (err) => {
      loadMsg.value = `GLB 未就绪或加载失败: ${err?.message || err}`
    },
  )

  const tick = () => {
    animationId = requestAnimationFrame(tick)
    controls.update()
    renderer.render(scene, camera)
  }
  tick()
}

function setMaterialMode(mode) {
  materialMode.value = mode
  if (!loadedRoot) return
  loadedRoot.traverse((obj) => {
    if (!obj.isMesh) return
    if (mode === 'original') {
      const original = originalMaterials.get(obj.uuid)
      if (original) obj.material = original
      return
    }
    // DoubleSide 对蝴蝶翅膀等薄面资产尤其重要。
    obj.material = new THREE.MeshStandardMaterial({
      color: 0xb9c0c8,
      roughness: 0.72,
      metalness: 0.0,
      side: THREE.DoubleSide,
    })
  })
}

function resize() {
  if (!stageRef.value || !renderer) return
  const w = stageRef.value.clientWidth
  const h = stageRef.value.clientHeight
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  renderer.setSize(w, h, false)
  annRef.value.width = w
  annRef.value.height = h
  drawAnns()
}

function drawAnns() {
  const c = annRef.value
  if (!c) return
  const ctx = c.getContext('2d')
  ctx.clearRect(0, 0, c.width, c.height)
  const all = draft ? [...anns, draft] : anns
  for (const a of all) {
    ctx.strokeStyle = a.color || '#ff4d4f'
    ctx.fillStyle = a.color || '#ff4d4f'
    ctx.lineWidth = 2
    if (a.type === 'rect') {
      ctx.strokeRect(a.x, a.y, a.w, a.h)
    } else if (a.type === 'arrow') {
      drawArrow(ctx, a.x1, a.y1, a.x2, a.y2)
    } else if (a.type === 'text') {
      ctx.font = '16px sans-serif'
      ctx.fillText(a.text || '', a.x, a.y)
    }
  }
}

function drawArrow(ctx, x1, y1, x2, y2) {
  const head = 10
  const angle = Math.atan2(y2 - y1, x2 - x1)
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6))
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6))
  ctx.stroke()
}

function relPos(ev) {
  const rect = stageRef.value.getBoundingClientRect()
  return { x: ev.clientX - rect.left, y: ev.clientY - rect.top }
}

function onPointerDown(ev) {
  if (tool.value === 'orbit') {
    enterInteractiveView()
    return
  }
  enterInteractiveView()
  const p = relPos(ev)
  if (tool.value === 'rect') {
    draft = { type: 'rect', x: p.x, y: p.y, w: 0, h: 0, color: color.value }
  } else if (tool.value === 'arrow') {
    draft = { type: 'arrow', x1: p.x, y1: p.y, x2: p.x, y2: p.y, color: color.value }
  } else if (tool.value === 'text') {
    const text = prompt('批注文字', '注意这里')
    if (text) anns.push({ type: 'text', x: p.x, y: p.y, text, color: color.value })
    drawAnns()
  }
}

function onPointerMove(ev) {
  if (!draft) return
  const p = relPos(ev)
  if (draft.type === 'rect') {
    draft.w = p.x - draft.x
    draft.h = p.y - draft.y
  } else if (draft.type === 'arrow') {
    draft.x2 = p.x
    draft.y2 = p.y
  }
  drawAnns()
}

function onPointerUp() {
  if (draft) {
    anns.push(draft)
    draft = null
    drawAnns()
  }
}

function enterInteractiveView() {
  showFixedPreview.value = false
}

watch(tool, (v) => {
  if (controls) controls.enabled = v === 'orbit'
  if (v !== 'orbit') enterInteractiveView()
  if (threeRef.value) {
    threeRef.value.style.pointerEvents = v === 'orbit' ? 'auto' : 'none'
  }
})

async function saveAnns() {
  const items = anns.map((a) => ({
    type: a.type,
    geometry: a,
    camera_snapshot: {
      position: camera.position.toArray(),
      target: controls.target.toArray(),
    },
  }))
  await api(`/api/assets/${route.params.id}/annotations`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  loadMsg.value = '批注已保存'
}

function exportJson() {
  const blob = new Blob([JSON.stringify(anns, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `asset-${route.params.id}-annotations.json`
  a.click()
}

function exportPng() {
  // 合成 three + ann
  const out = document.createElement('canvas')
  out.width = threeRef.value.width
  out.height = threeRef.value.height
  const ctx = out.getContext('2d')
  ctx.drawImage(threeRef.value, 0, 0)
  ctx.drawImage(annRef.value, 0, 0)
  const a = document.createElement('a')
  a.href = out.toDataURL('image/png')
  a.download = `asset-${route.params.id}-annotated.png`
  a.click()
}

async function saveTags() {
  const tags = tagInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
  asset.value = await api(`/api/assets/${route.params.id}/tags`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  })
}

async function retryAutoTag() {
  asset.value = await api(`/api/assets/${route.params.id}/auto-tag`, { method: 'POST' })
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
}

onMounted(async () => {
  await loadAsset()
  initThree()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  if (animationId) cancelAnimationFrame(animationId)
  controls?.dispose()
  renderer?.dispose()
})
</script>

<style scoped>
.layout { display: grid; grid-template-columns: 1fr 300px; gap: 1rem; }
.toolbar { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem; align-items: center; }
.toolbar .active { outline: 2px solid var(--accent); }
.stage { position: relative; width: 100%; height: min(70vh, 720px); background: #0b1016; border-radius: 8px; overflow: hidden; }
.three, .ann { position: absolute; inset: 0; width: 100%; height: 100%; }
.fixed-preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #0b1016;
  pointer-events: none;
  z-index: 1;
}
.fixed-preview-hint {
  position: absolute;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  color: #d7e2ee;
  background: rgba(15, 20, 25, 0.72);
  font-size: 0.8rem;
  pointer-events: none;
  z-index: 2;
}
.ann { pointer-events: none; }
.three { pointer-events: auto; }
.stage { pointer-events: auto; }
.side { display: grid; gap: 0.75rem; align-content: start; }
.tags { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.hint { color: var(--muted); }
.err { color: var(--err); font-size: 0.85rem; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
