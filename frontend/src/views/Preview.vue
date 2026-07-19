<template>
  <div v-if="asset" class="layout">
    <section class="viewer-panel card">
      <div class="toolbar">
        <button class="secondary" :class="{ active: tool === 'orbit' }" @click="setTool('orbit')">旋转</button>
        <button class="secondary" :class="{ active: materialMode === 'clay' }" @click="setMaterialMode('clay')">灰模</button>
        <button class="secondary" :class="{ active: materialMode === 'original' }" @click="setMaterialMode('original')">原材质</button>
        <span class="toolbar-sep" />
        <button class="secondary" :class="{ active: tool === 'select' }" @click="setTool('select')">选择</button>
        <button class="secondary" :class="{ active: tool === 'rect' }" @click="setTool('rect')">色框</button>
        <button class="secondary" :class="{ active: tool === 'arrow' }" @click="setTool('arrow')">箭头</button>
        <button class="secondary" :class="{ active: tool === 'text' }" @click="setTool('text')">文字</button>
        <input type="color" v-model="color" title="颜色" />
        <button class="secondary" :disabled="!selectedId" @click="deleteSelected">删除选中</button>
        <button @click="saveAnns">保存批注</button>
        <button class="secondary" @click="exportPng">导出 PNG</button>
        <button class="secondary" @click="exportJson">导出 JSON</button>
        <span class="badge">{{ gpuLabel }}</span>
        <span class="badge" :class="statusClass(asset.status)">{{ asset.status }}</span>
      </div>
      <p class="mode-hint">{{ modeHint }}</p>
      <div
        ref="stageRef"
        class="stage"
        @wheel="enterInteractiveView"
        @touchstart.passive="enterInteractiveView"
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
        <canvas
          ref="annRef"
          class="ann"
          :class="{ editing: isAnnotating }"
          @mousedown="onAnnPointerDown"
          @mousemove="onAnnPointerMove"
          @mouseup="onAnnPointerUp"
          @mouseleave="onAnnPointerUp"
          @dblclick="onAnnDblClick"
        ></canvas>
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
        <span v-for="t in asset.tags" :key="t.id" class="tag-chip">
          <span>{{ t.tag }}</span>
          <button type="button" class="tag-del" title="删除标签" @click="removeTag(t)">×</button>
        </span>
      </div>
      <p v-if="asset.error_message" class="err">{{ asset.error_message }}</p>
      <router-link to="/">← 返回资产库</router-link>
    </aside>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { api, statusClass } from '../api'

const HANDLE = 8
const HIT_PAD = 6

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
const selectedId = ref(null)

const isAnnotating = computed(() => tool.value !== 'orbit')
const modeHint = computed(() => {
  if (tool.value === 'orbit') return '当前：3D 交互（旋转/缩放）。点「色框 / 箭头 / 文字 / 选择」进入批注编辑。'
  if (tool.value === 'select') return '当前：批注选择。拖动可移动；色框可拖角点改大小；双击文字可改内容；Delete 删除。Esc /「旋转」退出。'
  if (tool.value === 'rect') return '当前：绘制色框。拖拽画框；可再点「选择」调整。Esc /「旋转」退出编辑并恢复 3D 交互。'
  if (tool.value === 'arrow') return '当前：绘制箭头。拖拽确定方向。Esc /「旋转」退出编辑。'
  if (tool.value === 'text') return '当前：放置文字。单击落点输入内容。Esc /「旋转」退出编辑。'
  return ''
})

let renderer, scene, camera, controls, animationId
let loadedRoot = null
let fallbackLights = []
const originalMaterials = new Map()
let anns = []
let draft = null
let drag = null
let interactiveAt = 0

function newAnnId() {
  return `ann-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function normalizeRect(a) {
  const x2 = a.x + a.w
  const y2 = a.y + a.h
  const x = Math.min(a.x, x2)
  const y = Math.min(a.y, y2)
  return { ...a, x, y, w: Math.abs(a.w), h: Math.abs(a.h) }
}

function setTool(next) {
  tool.value = next
  if (next === 'orbit') {
    selectedId.value = null
    draft = null
    drag = null
    drawAnns()
  } else {
    enterInteractiveView()
    selectedId.value = null
    draft = null
    drag = null
  }
  syncInteractionMode()
}

function exitToOrbit() {
  setTool('orbit')
  loadMsg.value = loadMsg.value?.startsWith('批注') ? loadMsg.value : '已退出批注编辑，可旋转/缩放模型'
}

function syncInteractionMode() {
  const orbit = tool.value === 'orbit'
  if (controls) controls.enabled = orbit
  if (threeRef.value) threeRef.value.style.pointerEvents = orbit ? 'auto' : 'none'
  if (annRef.value) {
    annRef.value.style.pointerEvents = orbit ? 'none' : 'auto'
    annRef.value.style.cursor = orbit ? 'default' : tool.value === 'select' ? 'default' : 'crosshair'
  }
}

async function loadAsset() {
  asset.value = await api(`/api/assets/${route.params.id}`)
  // 默认材质：GLB/GLTF 偏原材质；FBX/OBJ/BLEND 等 GLB 加载后再按是否含原材质判定。
  const ext = asset.value.ext?.toLowerCase()
  if (ext === '.glb' || ext === '.gltf') {
    materialMode.value = 'original'
  } else {
    materialMode.value = 'clay'
  }
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
  const existing = await api(`/api/assets/${route.params.id}/annotations`)
  anns = existing.map((a) => ({
    id: newAnnId(),
    type: a.type,
    ...a.geometry,
    color: a.geometry.color || '#ff4d4f',
  }))
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
      setMaterialMode(defaultMaterialModeForLoadedAsset(loadedRoot))
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
      syncInteractionMode()
    },
    undefined,
    (err) => {
      loadMsg.value = `GLB 未就绪或加载失败: ${err?.message || err}`
    },
  )

  canvas.addEventListener('pointerdown', enterInteractiveView)
  const tick = () => {
    animationId = requestAnimationFrame(tick)
    controls.update()
    renderer.render(scene, camera)
  }
  tick()
  syncInteractionMode()
}

function glbHasOriginalMaterials(root) {
  let found = false
  root.traverse((obj) => {
    if (found || !obj.isMesh || !obj.material) return
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const m of mats) {
      if (!m) continue
      if (m.map || m.normalMap || m.emissiveMap || m.metalnessMap || m.roughnessMap || m.aoMap || m.alphaMap) {
        found = true
        return
      }
      if (m.vertexColors) {
        found = true
        return
      }
      if (m.color) {
        const { r, g, b } = m.color
        const spread = Math.max(r, g, b) - Math.min(r, g, b)
        if (spread > 0.06) {
          found = true
          return
        }
        if (Math.abs(r - 0.8) > 0.12 || Math.abs(g - 0.8) > 0.12 || Math.abs(b - 0.8) > 0.12) {
          if (Math.max(r, g, b) > 0.15 && Math.min(r, g, b) < 0.95) {
            found = true
            return
          }
        }
      }
      if (m.emissive && m.emissive.r + m.emissive.g + m.emissive.b > 0.05) {
        found = true
        return
      }
    }
  })
  return found
}

function defaultMaterialModeForLoadedAsset(root) {
  const ext = asset.value?.ext?.toLowerCase()
  if (ext === '.glb' || ext === '.gltf') return 'original'
  // FBX/OBJ/BLEND：有原材质则默认展示原材质，否则灰模。
  if (ext === '.fbx' || ext === '.obj' || ext === '.blend') {
    return glbHasOriginalMaterials(root) ? 'original' : 'clay'
  }
  return 'clay'
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
    ctx.lineWidth = a.id === selectedId.value ? 3 : 2
    if (a.type === 'rect') {
      const r = normalizeRect(a)
      ctx.strokeRect(r.x, r.y, r.w, r.h)
    } else if (a.type === 'arrow') {
      drawArrow(ctx, a.x1, a.y1, a.x2, a.y2)
    } else if (a.type === 'text') {
      ctx.font = '16px sans-serif'
      ctx.fillText(a.text || '', a.x, a.y)
    }
    if (a.id && a.id === selectedId.value) drawSelection(ctx, a)
  }
}

function drawSelection(ctx, a) {
  ctx.save()
  ctx.strokeStyle = '#3d9cf0'
  ctx.fillStyle = '#3d9cf0'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 3])
  if (a.type === 'rect') {
    const r = normalizeRect(a)
    ctx.strokeRect(r.x - 2, r.y - 2, r.w + 4, r.h + 4)
    ctx.setLineDash([])
    for (const [hx, hy] of rectHandles(r)) {
      ctx.fillRect(hx - HANDLE / 2, hy - HANDLE / 2, HANDLE, HANDLE)
    }
  } else if (a.type === 'arrow') {
    ctx.setLineDash([])
    ctx.fillRect(a.x1 - HANDLE / 2, a.y1 - HANDLE / 2, HANDLE, HANDLE)
    ctx.fillRect(a.x2 - HANDLE / 2, a.y2 - HANDLE / 2, HANDLE, HANDLE)
  } else if (a.type === 'text') {
    const w = Math.max(ctx.measureText(a.text || '').width, 24)
    ctx.strokeRect(a.x - 4, a.y - 16, w + 8, 22)
  }
  ctx.restore()
}

function rectHandles(r) {
  const { x, y, w, h } = r
  return [
    [x, y],
    [x + w, y],
    [x, y + h],
    [x + w, y + h],
  ]
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
  const rect = annRef.value.getBoundingClientRect()
  return { x: ev.clientX - rect.left, y: ev.clientY - rect.top }
}

function hitTest(p) {
  for (let i = anns.length - 1; i >= 0; i -= 1) {
    const a = anns[i]
    if (a.type === 'rect') {
      const r = normalizeRect(a)
      const handles = rectHandles(r)
      for (let hi = 0; hi < handles.length; hi += 1) {
        const [hx, hy] = handles[hi]
        if (Math.abs(p.x - hx) <= HANDLE && Math.abs(p.y - hy) <= HANDLE) {
          return { ann: a, mode: 'resize', handle: hi }
        }
      }
      if (p.x >= r.x - HIT_PAD && p.x <= r.x + r.w + HIT_PAD && p.y >= r.y - HIT_PAD && p.y <= r.y + r.h + HIT_PAD) {
        return { ann: a, mode: 'move' }
      }
    } else if (a.type === 'arrow') {
      if (Math.hypot(p.x - a.x1, p.y - a.y1) <= HANDLE + 2) return { ann: a, mode: 'endpoint', which: 'start' }
      if (Math.hypot(p.x - a.x2, p.y - a.y2) <= HANDLE + 2) return { ann: a, mode: 'endpoint', which: 'end' }
      if (distToSegment(p.x, p.y, a.x1, a.y1, a.x2, a.y2) <= HIT_PAD + 2) return { ann: a, mode: 'move' }
    } else if (a.type === 'text') {
      const c = annRef.value.getContext('2d')
      c.font = '16px sans-serif'
      const w = Math.max(c.measureText(a.text || '').width, 24)
      if (p.x >= a.x - 4 && p.x <= a.x + w + 4 && p.y >= a.y - 16 && p.y <= a.y + 6) {
        return { ann: a, mode: 'move' }
      }
    }
  }
  return null
}

function distToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy || 1
  let t = ((px - x1) * dx + (py - y1) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

function onAnnPointerDown(ev) {
  if (!isAnnotating.value) return
  enterInteractiveView()
  const p = relPos(ev)

  if (tool.value === 'select' || ev.shiftKey) {
    const hit = hitTest(p)
    if (hit) {
      selectedId.value = hit.ann.id
      Object.assign(hit.ann, normalizeIfRect(hit.ann))
      drag = {
        mode: hit.mode,
        handle: hit.handle,
        which: hit.which,
        id: hit.ann.id,
        start: p,
        origin: snapshotAnn(hit.ann),
      }
      drawAnns()
      return
    }
    selectedId.value = null
    drawAnns()
    return
  }

  if (tool.value === 'rect') {
    selectedId.value = null
    draft = { id: newAnnId(), type: 'rect', x: p.x, y: p.y, w: 0, h: 0, color: color.value }
    drag = { mode: 'create' }
  } else if (tool.value === 'arrow') {
    selectedId.value = null
    draft = { id: newAnnId(), type: 'arrow', x1: p.x, y1: p.y, x2: p.x, y2: p.y, color: color.value }
    drag = { mode: 'create' }
  } else if (tool.value === 'text') {
    const text = prompt('批注文字', '注意这里')
    if (text) {
      anns.push({ id: newAnnId(), type: 'text', x: p.x, y: p.y, text, color: color.value })
      selectedId.value = anns[anns.length - 1].id
      drawAnns()
    }
  }
}

function normalizeIfRect(a) {
  return a.type === 'rect' ? normalizeRect(a) : a
}

function snapshotAnn(a) {
  return JSON.parse(JSON.stringify(a))
}

function onAnnPointerMove(ev) {
  if (!isAnnotating.value) return
  const p = relPos(ev)

  if (draft && drag?.mode === 'create') {
    if (draft.type === 'rect') {
      draft.w = p.x - draft.x
      draft.h = p.y - draft.y
    } else if (draft.type === 'arrow') {
      draft.x2 = p.x
      draft.y2 = p.y
    }
    drawAnns()
    return
  }

  if (!drag || !drag.id) {
    if (tool.value === 'select') {
      const hit = hitTest(p)
      annRef.value.style.cursor = hit
        ? hit.mode === 'resize' || hit.mode === 'endpoint'
          ? 'nwse-resize'
          : 'move'
        : 'default'
    }
    return
  }

  const ann = anns.find((a) => a.id === drag.id)
  if (!ann) return
  const dx = p.x - drag.start.x
  const dy = p.y - drag.start.y
  const o = drag.origin

  if (drag.mode === 'move') {
    if (ann.type === 'rect') {
      ann.x = o.x + dx
      ann.y = o.y + dy
      ann.w = o.w
      ann.h = o.h
    } else if (ann.type === 'arrow') {
      ann.x1 = o.x1 + dx
      ann.y1 = o.y1 + dy
      ann.x2 = o.x2 + dx
      ann.y2 = o.y2 + dy
    } else if (ann.type === 'text') {
      ann.x = o.x + dx
      ann.y = o.y + dy
    }
  } else if (drag.mode === 'resize' && ann.type === 'rect') {
    let x1 = o.x
    let y1 = o.y
    let x2 = o.x + o.w
    let y2 = o.y + o.h
    if (drag.handle === 0) {
      x1 = o.x + dx
      y1 = o.y + dy
    } else if (drag.handle === 1) {
      x2 = o.x + o.w + dx
      y1 = o.y + dy
    } else if (drag.handle === 2) {
      x1 = o.x + dx
      y2 = o.y + o.h + dy
    } else if (drag.handle === 3) {
      x2 = o.x + o.w + dx
      y2 = o.y + o.h + dy
    }
    Object.assign(ann, normalizeRect({ ...ann, x: x1, y: y1, w: x2 - x1, h: y2 - y1 }))
  } else if (drag.mode === 'endpoint' && ann.type === 'arrow') {
    if (drag.which === 'start') {
      ann.x1 = o.x1 + dx
      ann.y1 = o.y1 + dy
    } else {
      ann.x2 = o.x2 + dx
      ann.y2 = o.y2 + dy
    }
  }
  drawAnns()
}

function onAnnPointerUp() {
  if (draft) {
    if (draft.type === 'rect') {
      const r = normalizeRect(draft)
      if (r.w >= 4 && r.h >= 4) {
        anns.push(r)
        selectedId.value = r.id
      }
    } else if (draft.type === 'arrow') {
      if (Math.hypot(draft.x2 - draft.x1, draft.y2 - draft.y1) >= 4) {
        anns.push(draft)
        selectedId.value = draft.id
      }
    }
    draft = null
  }
  drag = null
  drawAnns()
}

function onAnnDblClick(ev) {
  if (!isAnnotating.value) return
  const hit = hitTest(relPos(ev))
  if (!hit || hit.ann.type !== 'text') return
  selectedId.value = hit.ann.id
  const next = prompt('修改文字', hit.ann.text || '')
  if (next != null) {
    hit.ann.text = next
    drawAnns()
  }
}

function deleteSelected() {
  if (!selectedId.value) return
  anns = anns.filter((a) => a.id !== selectedId.value)
  selectedId.value = null
  drawAnns()
  loadMsg.value = '已删除选中批注（记得保存）'
}

function onKeyDown(ev) {
  if (ev.key === 'Escape') {
    if (isAnnotating.value) {
      ev.preventDefault()
      exitToOrbit()
    }
    return
  }
  if (!isAnnotating.value) return
  if ((ev.key === 'Delete' || ev.key === 'Backspace') && selectedId.value) {
    const tag = ev.target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    ev.preventDefault()
    deleteSelected()
  }
}

function enterInteractiveView() {
  showFixedPreview.value = false
}

watch(tool, () => syncInteractionMode())

async function saveAnns() {
  const items = anns.map((a) => {
    const geometry =
      a.type === 'rect'
        ? normalizeRect(a)
        : a
    const { id: _id, type, ...rest } = geometry
    return {
      type: a.type,
      geometry: { type: a.type, ...rest },
      camera_snapshot: {
        position: camera.position.toArray(),
        target: controls.target.toArray(),
      },
    }
  })
  await api(`/api/assets/${route.params.id}/annotations`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  loadMsg.value = '批注已保存，已退出编辑并恢复 3D 交互'
  setTool('orbit')
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
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
}

async function removeTag(tag) {
  const tags = asset.value.tags.filter((t) => t.id !== tag.id).map((t) => t.tag)
  asset.value = await api(`/api/assets/${route.params.id}/tags`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  })
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
}

async function retryAutoTag() {
  asset.value = await api(`/api/assets/${route.params.id}/auto-tag`, { method: 'POST' })
  tagInput.value = asset.value.tags.map((t) => t.tag).join(', ')
}

onMounted(async () => {
  await loadAsset()
  initThree()
  window.addEventListener('resize', resize)
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  window.removeEventListener('keydown', onKeyDown)
  if (animationId) cancelAnimationFrame(animationId)
  controls?.dispose()
  renderer?.dispose()
})
</script>

<style scoped>
.layout { display: grid; grid-template-columns: 1fr 300px; gap: 1rem; }
.toolbar { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.35rem; align-items: center; }
.toolbar .active { outline: 2px solid var(--accent); }
.toolbar-sep { width: 1px; height: 1.4rem; background: var(--border); margin: 0 0.15rem; }
.mode-hint { margin: 0 0 0.65rem; color: var(--muted); font-size: 0.85rem; }
.stage { position: relative; width: 100%; height: min(70vh, 720px); background: #0b1016; border-radius: 8px; overflow: hidden; pointer-events: auto; }
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
.ann { pointer-events: none; z-index: 3; }
.ann.editing { pointer-events: auto; }
.three { pointer-events: auto; z-index: 0; }
.side { display: grid; gap: 0.75rem; align-content: start; }
.tags { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.15rem 0.25rem 0.15rem 0.5rem;
  border-radius: 999px;
  background: #243040;
  border: 1px solid var(--border);
  font-size: 0.78rem;
  color: var(--muted);
}
.tag-del {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 0 0.3rem;
  cursor: pointer;
  line-height: 1;
}
.tag-del:hover { color: var(--err); }
.hint { color: var(--muted); }
.err { color: var(--err); font-size: 0.85rem; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
</style>
