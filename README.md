# DAM 3D Render

面向 3D 游戏资产的单机 DAM（Digital Asset Management）研究原型，提供资产入库、格式预处理、浏览器预览、图文检索、自动/手动打标和批注功能。

- 产品需求：[docs/PRD.md](docs/PRD.md)
- 更新日志：[docs/CHANGELOG.md](docs/CHANGELOG.md)
- 前端：http://127.0.0.1:5173
- 后端 API：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs

## 功能特点

### 资产入库与托管

- 支持浏览器单文件上传。
- 支持扫描本地目录并增量导入。
- 原始文件复制到 DAM 托管库，预处理不会覆盖或修改原件。
- 非预览白名单格式仍可入库保管，并标记为 `preview_unsupported`。
- 预处理在后台异步执行，页面显示 `copied`、`processing`、`ready` 或 `failed` 状态。

### 分格式预处理

不同格式使用独立适配策略，格式专用修复不会影响其他格式。

| 格式 | 当前处理方式 |
|------|--------------|
| BLEND | Blender 直接打开原场景，过滤明显辅助对象，薄片资产可自适应正面取景 |
| OBJ | Blender 导入并保留全部网格和独立部件，再转换为 GLB |
| FBX | Blender 导入并保留全部网格和独立部件，再转换为 GLB |
| GLTF | Blender 导入后打包为浏览器预览用 GLB |
| GLB | 原文件直接复制为预览文件，不进行 Blender 二次导出；Blender 只生成固定多视图 |

GLB 直接预览会保留 Three.js 支持的 PBR 材质、顶点颜色、内嵌贴图、透明度、动画与 `KHR_lights_punctual` 灯光扩展。

### 秒级浏览器预览

- Three.js 加载 GLB，支持旋转、缩放和平移。
- 自动检测 WebGL/GPU，并优先使用高性能 GPU。
- 页面显示从加载到可交互的耗时，目标为不超过 2 秒。
- 提供“灰模”和“原材质”两种显示方式。
- 灰模采用中性双面材质和兜底三点布光，确保深色、薄面资产可见。
- GLB 默认使用原材质；存在内嵌灯光时优先使用文件灯光，否则使用查看器兜底灯光。
- 资产库卡片和预览页默认首帧使用同一张固定图；拖动、滚轮或触摸后切换到实时 3D。

### 图文相似检索

- 使用本地 SigLIP2 统一编码文字和图片。
- 每个资产的多视图分别生成向量并写入 faiss。
- 检索后按资产聚合，取最佳视图得分作为资产相似度。
- 默认返回 Top-K=10，可在设置中修改。
- Top-1 最大化显示，其余结果按相似度排序。
- 文字检索可叠加手动标签和自动标签匹配分。

### 标签

- 支持用户手动增加、删除资产标签。
- 支持通过 OpenRouter 调用 Gemini 多模态模型自动打标。
- 自动打标输入为 Blender 生成的多视图图片，不直接上传 3D 原件。
- 未配置 API Key 或打标失败不会阻断入库、预览和检索。

### 批注

- 支持矩形色框、箭头和文字。
- 批注以 2D 画布方式叠加在 3D 预览上。
- 支持持久化保存和重新加载。
- 支持导出带批注 PNG 和批注 JSON。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11、FastAPI、SQLAlchemy |
| 元数据 | SQLite |
| 向量索引 | faiss `IndexFlatIP` + 外部 ID 映射 |
| Embedding | `google/siglip2-so400m-patch16-512` |
| 3D 预处理 | Blender 5.0 无头模式 |
| 前端 | Vue 3、Vite |
| 3D 查看器 | Three.js、GLTFLoader、OrbitControls |
| 自动打标 | OpenRouter、Gemini 3 Pro |

## 默认路径

| 用途 | 路径 |
|------|------|
| 项目 | `E:\code\Projects\DAM_3D_Render` |
| 测试资产 | `E:\code\Data\3D\CC` |
| DAM 托管库 | `E:\code\Data\DAM_Library` |
| Blender | `D:\Program Files (x86)\Blender Foundation\Blender 5.0\blender.exe` |
| SigLIP2 权重 | `E:\Weights\VLM\siglip2-so400m-patch16-512` |
| 本地配置 | `backend\config.local.json` |

所有默认路径均可在代码配置或设置页中调整。

## 环境准备

### 后端

```powershell
conda activate cs224n
cd E:\code\Projects\DAM_3D_Render\backend
pip install -r requirements.txt
```

确认以下依赖可用：

```powershell
python -c "import fastapi, torch, faiss, transformers; print('backend dependencies ok')"
```

### 前端

当前前端兼容 Node.js 18+。

```powershell
cd E:\code\Projects\DAM_3D_Render\frontend
npm install
```

### Blender

确认默认路径存在：

```powershell
Test-Path "D:\Program Files (x86)\Blender Foundation\Blender 5.0\blender.exe"
```

如果 Blender 安装在其他目录，请在设置页修改路径。

## 启动

打开两个 PowerShell 终端。

### 终端一：后端

```powershell
conda activate cs224n
cd E:\code\Projects\DAM_3D_Render\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端启动时会尝试加载 SigLIP2。权重较大，首次加载可能需要等待。

### 终端二：前端

```powershell
cd E:\code\Projects\DAM_3D_Render\frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：http://127.0.0.1:5173

## 操作指南

### 1. 配置系统

进入顶部“设置”页面，确认或修改：

1. DAM 托管库根目录。
2. Blender 可执行文件路径。
3. SigLIP2 本地权重路径。
4. 默认 Top-K。
5. 多视图数量。
6. 视觉相似度权重 α 与标签权重 β。
7. 自动打标开关和 prompt。
8. OpenRouter API Key。

API Key 只保存到本地 `backend/config.local.json`，该文件已加入 `.gitignore`。

### 2. 导入资产

进入“资产库”页面：

- 单个文件：点击“上传文件”。
- 本地目录：输入目录路径后点击“扫描入库”。

建议首次测试仅导入少量文件。`E:\code\Data\3D\CC` 当前包含较多测试资产，扫描整个目录会触发大量 Blender 与 Embedding 任务。

### 3. 查看处理状态

- `copied`：原件已复制。
- `processing`：正在转换、渲染多视图或生成向量。
- `ready`：可预览和检索。
- `preview_unsupported`：已保管原件，但格式不支持 3D 预览。
- `failed`：预处理失败，可查看错误信息（v1.2 起入库后不再提供「重处理」）。

### 4. 预览资产

点击资产卡片的预览画面（黑色背景缩略图区域）进入预览页：

1. 默认先显示与资产卡片完全相同的固定图。
2. 拖动、滚轮或触摸画面后进入实时 3D。
3. 使用“灰模 / 原材质”切换显示方式。
4. 鼠标左键旋转，滚轮缩放，OrbitControls 支持平移。

GLB 默认进入“原材质”；OBJ、FBX、BLEND 默认进入“灰模”。

### 5. 添加批注

1. 选择“色框”“箭头”或“文字”。
2. 选择颜色。
3. 在画布中绘制或输入文字。
4. 点击“保存批注”。
5. 使用“导出 PNG”导出带批注图片。
6. 使用“导出 JSON”导出结构化批注。

### 6. 手动和自动打标

- 在资产详情侧栏输入逗号分隔标签并保存。
- 配置 OpenRouter API Key 后，点击“重试自动打标”。
- 未配置 Key 时 `tag_status` 显示 `skipped`，不影响其他功能。

### 7. 图文检索

进入“检索”页面：

- 文字检索：输入资产描述并提交。
- 以图搜图：上传参考图片。

结果页会突出显示 Top-1，并在下方显示其余 Top-K−1。

## 托管库结构

```text
E:\code\Data\DAM_Library\
  originals\            # 原件副本，按 asset_id 管理
  previews\
    glb\                 # 浏览器预览 GLB
    views\               # 多视图固定图
  embeddings\           # 向量旁路数据
  annotations\          # 批注 JSON
  faiss\
    views.index          # faiss 视图级索引
    views_meta.json      # 索引元信息
  dam.sqlite3            # 元数据库
```

不要手动修改 `originals` 中的原件。删除或重建衍生品应通过系统接口完成。

## OBJ/MTL 与 GLTF/BIN

PRD v1.1 已定义完整的“主资产 + 依赖文件包”规范：

- OBJ 通过 `mtllib` 关联 MTL，MTL 再关联纹理。
- GLTF 通过 `buffers[].uri` 和 `images[].uri` 关联 BIN 与纹理。
- 依赖文件不应作为独立资产显示。
- 缺少 MTL 时允许使用中性材质继续预览。
- 缺少必要 BIN 时不得生成空白 GLB。
- 依赖路径必须限制在资产包目录内。

**当前原型限制：**前端上传入口仍以单文件为主，多文件/文件夹/ZIP 资产包及依赖补充界面尚未全部实现。导入带外部依赖的 OBJ 或 GLTF 前，应确保依赖文件位于主文件声明的相对路径中；完整实现要求以 [PRD v1.1](docs/PRD.md) 为准。

GLB 是单文件容器，不存在上述 sidecar 管理问题，因此推荐交换与交付时优先使用 GLB。

## 验证与测试

### 后端语法检查

```powershell
cd E:\code\Projects\DAM_3D_Render\backend
python -m compileall app
```

### 前端构建检查

```powershell
cd E:\code\Projects\DAM_3D_Render\frontend
npm run build
```

### 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

预期：

```json
{"ok": true}
```

### 基准测试资产

| 文件 | 主要验证内容 |
|------|--------------|
| `butterfly.blend` | BLEND 主体过滤、薄片资产取景 |
| `锦鲤.blend` | BLEND 灰模与交互预览 |
| `All_Stylized_ship.obj` | OBJ 多部件完整保留 |
| `All_Stylized_ship.fbx` | FBX 回归对照 |
| `12 Watermelon.glb` | GLB 原生材质、固定图、原文件哈希一致性 |

自动化测试生成的 `probe.bin` 等临时资产必须在测试后删除，不能残留在正式资产库。

## 常见问题

### 页面仍显示旧缩略图或旧前端

使用 `Ctrl+F5` 强制刷新浏览器缓存。

### 资产一直处于 processing

检查：

1. 后端终端是否仍在运行。
2. Blender 路径是否正确。
3. 磁盘是否有足够空间。
4. Blender 是否能在无头模式导入该格式。

### 模型过暗或材质不可见

- 先切换到“灰模”确认几何是否正常。
- GLB 切换“原材质”查看 PBR 结果。
- 含内嵌灯光的 GLB 使用文件灯光；无灯光时系统使用兜底布光。

### 文字或图片检索没有结果

检查设置页中的 Embedding 状态，并确认：

- SigLIP2 权重路径存在。
- 资产已经生成多视图。
- 资产状态为 `ready`。
- faiss 索引中已有向量。

### 自动打标显示 skipped

表示未配置 OpenRouter API Key 或自动打标已关闭。该状态不会影响入库、预览和检索。

### GLB 是否被系统修改

不会。GLB 预览文件由托管原件直接复制，可通过 SHA-256 验证二者完全一致。Blender 仅生成多视图固定图片。

## 当前范围与后续计划

当前是单机单用户研究原型，不包含账号、权限、多用户协作和云部署。

后续计划包括：

- OBJ/MTL/纹理和 GLTF/BIN/纹理的完整资产包上传与依赖补充。
- Qwen3-VL-Embedding 与 Qwen3-VL-Reranker。
- 3D 世界坐标锚定批注。
- 接近最终观感的 2 秒内渐进预览。
- 更高效的格式快速转换器，并在失败时回退 Blender。
