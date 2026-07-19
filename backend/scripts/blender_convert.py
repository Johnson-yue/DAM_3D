"""
Blender 后台脚本：由 blender --python 调用。
用法: blender --background --python blender_convert.py -- job.json

.blend 使用 open_mainfile；不改物体变换/层级（禁止 transform_apply）；
保留曲线等修饰器依赖；背景平面与离群体只排除出取景/导出；
程序 Base Color 烘成贴图后再导 GLB；有材质则渲原材质固定图。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _parse_args():
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        return sys.argv[idx + 1 :]
    return sys.argv[1:]


def clear_default_scene():
    import bpy
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.meshes):
        if block.users == 0:
            bpy.data.meshes.remove(block)


def open_blend(path: Path):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)


def import_external(path: Path):
    import bpy
    ext = path.suffix.lower()
    if ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        raise RuntimeError(f"不支持的扩展名: {ext}")


def _mesh_poly_count(obj) -> int:
    if obj.type != "MESH" or obj.data is None:
        return 0
    return len(obj.data.polygons)


def _is_thin_plane(obj) -> bool:
    dims = sorted(float(x) for x in obj.dimensions)
    if dims[2] <= 1e-6:
        return True
    if dims[0] / max(dims[2], 1e-8) < 0.02:
        return True
    return False


def _mesh_char_size(obj) -> float:
    """物体特征尺寸：最大边长，用于识别相对主体过大的辅助体。"""
    dims = [abs(float(x)) for x in obj.dimensions]
    return max(dims) if dims else 0.0


def _mesh_world_center(obj):
    """网格世界空间包围盒中心，用于主体簇距离过滤。"""
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    acc = Vector((0.0, 0.0, 0.0))
    for c in corners:
        acc += c
    return acc / 8.0


def prepare_asset_meshes(filter_blend_helpers=False, preserve_scene_lights=False):
    """
    准备参与导出和渲染的网格。

    OBJ / FBX / GLTF：保留全部网格。此类交换格式通常会把一个完整资产拆成
    大量独立小部件，不能按面数删除。

    BLEND：结构保真——不 transform_apply、不隐藏曲线等依赖物体；
    名称平面/极薄平面与尺寸·距离离群体只排除出取景与 GLB 选中集；
    作者相机/灯光不参与渲染。禁止按面数百分比删小部件。
    """
    import bpy
    from mathutils import Vector

    # 修饰器 / 约束常用依赖类型：隐藏会导致 ARRAY+CURVE、CLAMP_TO 等求值错位。
    _BLEND_DEPENDENCY_TYPES = {
        "CURVE",
        "EMPTY",
        "ARMATURE",
        "LATTICE",
        "FONT",
        "SURFACE",
        "META",
    }

    # GLB 可以包含多个 scene。Blender 导入后，非活动 scene 的对象不属于
    # 当前 ViewLayer，直接 select_set 会报错；缩略图只处理默认活动 scene。
    view_layer_names = {obj.name for obj in bpy.context.view_layer.objects}
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name in view_layer_names
    ]
    if not meshes:
        return []

    if filter_blend_helpers:
        candidates = [obj for obj in meshes if _mesh_poly_count(obj) > 0]

        def _is_named_plane(obj) -> bool:
            return "平面" in obj.name or "plane" in obj.name.lower()

        def _is_thin_floor(obj) -> bool:
            return _is_thin_plane(obj) and _mesh_poly_count(obj) <= 2

        # 优先尊重作者隐藏；若可见网格为空则回退全部候选。
        visible = [
            obj
            for obj in candidates
            if (not obj.hide_get()) and (not obj.hide_viewport) and (not obj.hide_render)
        ]
        pool0 = visible if visible else list(candidates)
        # 用全体候选估中位数，再判断「名叫 Plane 的是否过大」。
        # 避免沙滩椅座垫（名 Plane、尺寸≈椅架）被一律剔除。
        seed_sizes = sorted(_mesh_char_size(obj) for obj in pool0) or [1.0]
        seed_median = seed_sizes[len(seed_sizes) // 2]
        named_plane_cap = max(seed_median * 8.0, 1e-4)

        def _is_bg_plane(obj) -> bool:
            # 极薄少面：真正地板/衬板。
            if _is_thin_floor(obj):
                return True
            # 名称像平面：仅当相对主体过大才剔（大地板）；同尺寸零件保留。
            if _is_named_plane(obj) and _mesh_char_size(obj) > named_plane_cap:
                return True
            return False

        pool = [obj for obj in pool0 if not _is_bg_plane(obj)]
        if not pool:
            pool = [obj for obj in candidates if not _is_bg_plane(obj)]
        if not pool:
            return []

        sizes = [_mesh_char_size(obj) for obj in pool]
        ordered = sorted(sizes)
        median = ordered[len(ordered) // 2]
        size_cap = max(median * 8.0, 1e-4)
        keep = [obj for obj, sz in zip(pool, sizes) if sz <= size_cap]
        if not keep:
            keep = list(pool)

        # 空间主体簇：丢掉相对簇中心过远的孤立辅助体（尺寸可能仍接近中位数）。
        if len(keep) >= 3:
            centers = [_mesh_world_center(obj) for obj in keep]
            cx = sorted(float(c.x) for c in centers)[len(centers) // 2]
            cy = sorted(float(c.y) for c in centers)[len(centers) // 2]
            cz = sorted(float(c.z) for c in centers)[len(centers) // 2]
            med_c = Vector((cx, cy, cz))
            dists = [(obj, (c - med_c).length) for obj, c in zip(keep, centers)]
            d_vals = sorted(d for _, d in dists)
            med_d = d_vals[len(d_vals) // 2]
            # 距离上限：簇内典型跨度的数倍，且至少覆盖数个主体特征尺寸。
            dist_cap = max(med_d * 8.0, median * 8.0, 1e-4)
            clustered = [obj for obj, d in dists if d <= dist_cap]
            if clustered:
                keep = clustered
    else:
        # 交换格式可能包含成百上千个不同大小的零件，全部保留。
        keep = [obj for obj in meshes if _mesh_poly_count(obj) > 0]

    keep_set = set(keep)
    for obj in bpy.context.scene.objects:
        if obj.name not in view_layer_names:
            continue
        if obj.type == "MESH":
            # 未入选网格：仅 hide_render，不进固定图；不改 transform / 父子。
            if filter_blend_helpers and obj not in keep_set:
                obj.hide_render = True
            continue
        if filter_blend_helpers:
            # 曲线等依赖必须保持可用，否则树干 CURVE / 叶子 CLAMP_TO 会错位。
            if obj.type in _BLEND_DEPENDENCY_TYPES:
                continue
            if preserve_scene_lights and obj.type == "LIGHT":
                continue
            # 作者相机/灯光不参与我们的固定图渲染。
            if obj.type in ("CAMERA", "LIGHT"):
                obj.hide_render = True
            else:
                obj.hide_render = True
            continue
        if not (preserve_scene_lights and obj.type == "LIGHT"):
            obj.hide_render = True
            obj.hide_viewport = True

    # 确保主体可渲可导出；BLEND 禁止 transform_apply（会破坏父子局部坐标）。
    bpy.ops.object.select_all(action="DESELECT")
    for obj in keep:
        if obj.name not in view_layer_names:
            continue
        obj.hide_render = False
        obj.hide_viewport = False
        try:
            obj.hide_set(False)
        except Exception:
            pass
        obj.select_set(True)
    if keep:
        bpy.context.view_layer.objects.active = keep[0]
        if not filter_blend_helpers:
            try:
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            except Exception:
                pass
    return keep


def scene_bbox(objects):
    """用 depsgraph 求值后的包围盒（含 ARRAY/CURVE 等修饰器变形）。"""
    import bpy
    from mathutils import Vector

    depsgraph = bpy.context.evaluated_depsgraph_get()
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    has = False
    for obj in objects:
        if obj.type != "MESH":
            continue
        has = True
        obj_eval = obj.evaluated_get(depsgraph)
        for corner in obj_eval.bound_box:
            world = obj_eval.matrix_world @ Vector(corner)
            mins.x, mins.y, mins.z = min(mins.x, world.x), min(mins.y, world.y), min(mins.z, world.z)
            maxs.x, maxs.y, maxs.z = max(maxs.x, world.x), max(maxs.y, world.y), max(maxs.z, world.z)
    if not has:
        return None, None, None
    center = (mins + maxs) * 0.5
    size = (maxs - mins).length
    return center, max(size, 0.01), (mins, maxs)


def setup_camera_light(center, radius):
    import bpy
    import math
    from mathutils import Vector

    cam_data = bpy.data.cameras.new("DamCam")
    cam_data.clip_start = max(radius * 0.001, 0.001)
    cam_data.clip_end = max(radius * 100.0, 100.0)
    cam = bpy.data.objects.new("DamCam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    light_data = bpy.data.lights.new(name="DamLight", type="SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new(name="DamLight", object_data=light_data)
    bpy.context.collection.objects.link(light)
    light.location = center + Vector((radius, radius, radius))
    light.rotation_euler = (
        math.radians(32),
        math.radians(-28),
        math.radians(-28),
    )

    # GLB 的 EEVEE 彩色缩略图使用三点布光；WORKBENCH 分支不会受这些灯影响。
    fill_data = bpy.data.lights.new(name="DamFill", type="SUN")
    fill_data.energy = 1.4
    fill = bpy.data.objects.new(name="DamFill", object_data=fill_data)
    bpy.context.collection.objects.link(fill)
    fill.rotation_euler = (
        math.radians(58),
        math.radians(24),
        math.radians(145),
    )

    rim_data = bpy.data.lights.new(name="DamRim", type="SUN")
    rim_data.energy = 1.0
    rim = bpy.data.objects.new(name="DamRim", object_data=rim_data)
    bpy.context.collection.objects.link(rim)
    rim.rotation_euler = (
        math.radians(-42),
        math.radians(12),
        math.radians(210),
    )
    return cam, light


def view_dirs_for_bbox(mins, maxs):
    """按包围盒自动生成视角。

    扁平物体（蝴蝶）：front=面积最大面。
    瘦高物体（椰子树）：若最大面是顶/底，改用最大侧面作 front，避免库卡片俯视。
    """
    from mathutils import Vector
    size = maxs - mins
    # 各轴作为视线方向时，看见的是另外两轴张成的面
    faces = [
        ("x", float(size.y * size.z), Vector((1, 0, 0.25))),
        ("y", float(size.x * size.z), Vector((0, 1, 0.25))),
        ("z", float(size.x * size.y), Vector((0.25, 0.25, 1))),
    ]
    faces.sort(key=lambda x: x[1], reverse=True)
    height = float(size.z)
    footprint = max(float(size.x), float(size.y), 1e-8)
    # 明显偏高：顶视面积虽大也不作 front。
    if faces[0][0] == "z" and height > footprint * 0.55:
        sides = [f for f in faces if f[0] != "z"]
        sides.sort(key=lambda x: x[1], reverse=True)
        ordered = [sides[0], sides[1], faces[0]]
    else:
        ordered = faces
    primary = ordered[0][2].normalized()
    secondary = ordered[1][2].normalized()
    tertiary = ordered[2][2].normalized()
    return {
        "front": tuple(primary),
        "back": tuple(-primary),
        "right": tuple(secondary),
        "left": tuple(-secondary),
        "top": tuple(tertiary),
        "bottom": tuple(-tertiary),
        "extra_0": tuple((primary + secondary).normalized()),
        "extra_1": tuple((primary - secondary).normalized()),
    }


def _color_is_meaningful(r: float, g: float, b: float) -> bool:
    """接近中性灰/默认白的颜色不算“有原材质”；明显色差或饱和色才算。"""
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn > 0.06:
        return True
    # 非近灰的纯色（如明显偏橙/蓝）
    if abs(r - 0.8) > 0.12 or abs(g - 0.8) > 0.12 or abs(b - 0.8) > 0.12:
        if mx > 0.15 and mn < 0.95:
            return True
    return False


def scene_has_original_materials(objects) -> bool:
    """
    判断网格是否携带可展示的原材质（贴图、连接的 Base Color、或非中性颜色）。
    用于 FBX/OBJ：有则固定图走原材质渲染，无则仍用灰模。
    """
    import bpy

    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            if mat.use_nodes and mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and getattr(node, "image", None):
                        return True
                    if node.type == "BSDF_PRINCIPLED":
                        base = node.inputs.get("Base Color")
                        if base is None:
                            continue
                        if base.is_linked:
                            return True
                        c = base.default_value
                        if _color_is_meaningful(float(c[0]), float(c[1]), float(c[2])):
                            return True
                        for key in ("Emission Color", "Emission"):
                            em = node.inputs.get(key)
                            if em is None:
                                continue
                            if em.is_linked:
                                return True
                            if hasattr(em, "default_value"):
                                ev = em.default_value
                                if isinstance(ev, (list, tuple)) or hasattr(ev, "__getitem__"):
                                    if float(ev[0]) + float(ev[1]) + float(ev[2]) > 0.05:
                                        return True
            elif hasattr(mat, "diffuse_color"):
                c = mat.diffuse_color
                if _color_is_meaningful(float(c[0]), float(c[1]), float(c[2])):
                    return True
    return False


def _set_color_render_engine(scene) -> str:
    """Blender 4/5 的 EEVEE 枚举名不同，逐个尝试后再回退 Cycles。"""
    for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = name
            return name
        except Exception:
            continue
    scene.render.engine = "CYCLES"
    return "CYCLES"


def render_views(
    cam,
    center,
    radius,
    views_dir: Path,
    view_names,
    mins=None,
    maxs=None,
    use_original_materials=False,
):
    import bpy
    from mathutils import Vector

    scene = bpy.context.scene
    if use_original_materials:
        # 有原材质时：EEVEE/Cycles 渲染真实颜色与贴图。
        engine = _set_color_render_engine(scene)
        scene.world.use_nodes = True
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.06, 0.075, 0.095, 1.0)
            background.inputs["Strength"].default_value = 0.45
        # Blender 4/5：Look 枚举多为「Medium High Contrast」；
        # 「AgX - …」前缀在部分版本不存在，写错会直接打断预处理。
        for look in (
            "Medium High Contrast",
            "AgX - Medium High Contrast",
            "None",
        ):
            try:
                scene.view_settings.look = look
                break
            except Exception:
                continue
        scene.view_settings.exposure = 1.0 if engine.startswith("BLENDER_EEVEE") else 0.5
        # 确保外部/打包贴图尽量可用。
        for img in bpy.data.images:
            try:
                if img.filepath:
                    img.reload()
            except Exception:
                pass
    else:
        # 无原材质，或 GLTF 等仍走稳定灰模缩略图。
        try:
            scene.render.engine = "BLENDER_WORKBENCH"
            shading = scene.display.shading
            shading.light = "STUDIO"
            shading.color_type = "SINGLE"
            shading.single_color = (0.72, 0.75, 0.78)
            shading.show_shadows = True
            shading.show_cavity = True
            shading.cavity_type = "WORLD"
        except Exception:
            _set_color_render_engine(scene)

    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True

    from mathutils import Vector as _V
    if mins is not None and maxs is not None:
        vdirs = view_dirs_for_bbox(mins, maxs)
    else:
        vdirs = {
            "front": (0, -1, 0.35),
            "right": (1, 0, 0.35),
            "back": (0, 1, 0.35),
            "left": (-1, 0, 0.35),
            "top": (0.01, 0.01, 1),
            "bottom": (0.01, 0.01, -1),
            "extra_0": (0.7, -0.7, 0.5),
            "extra_1": (-0.7, -0.7, 0.5),
        }
    results = []
    dist = radius * 2.2
    for name in view_names:
        direction = vdirs.get(name, (0, -1, 0.35))
        d = Vector(direction).normalized()
        cam.location = center + d * dist
        direction_to = center - cam.location
        cam.rotation_euler = direction_to.to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = 50
        out = views_dir / f"{name}.png"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        results.append({"view_id": name, "path": str(out)})
    return results


def _material_needs_basecolor_bake(mat) -> bool:
    """Base Color 来自非图像节点（程序纹理 / ColorRamp 等）时，GLTF 导出会丢外观。"""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return False
    for node in mat.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        base = node.inputs.get("Base Color")
        if base is None or not base.is_linked:
            return False
        from_node = base.links[0].from_node
        if from_node.type == "TEX_IMAGE" and getattr(from_node, "image", None):
            return False
        return True
    return False


def _ensure_mesh_uv(obj) -> None:
    """有 UV 则保留；没有则 Smart UV Project（仅改 UV，不改几何）。"""
    import bpy

    if obj.type != "MESH" or obj.data is None:
        return
    if obj.data.uv_layers and len(obj.data.uv_layers) > 0:
        return
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.02)
    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _set_cycles_for_bake(scene) -> None:
    scene.render.engine = "CYCLES"
    try:
        scene.cycles.samples = 8
    except Exception:
        pass
    try:
        scene.cycles.device = "GPU"
    except Exception:
        try:
            scene.cycles.device = "CPU"
        except Exception:
            pass


def bake_blend_procedural_basecolors(keep_objects, size: int = 1024) -> int:
    """
    仅用于 .blend → GLB：把程序 Base Color 烘成 1024 贴图并接到 Principled，
    以便 glTF 交互预览与固定图观感接近。返回成功烘焙的材质数。
    """
    import bpy

    jobs = []
    seen_mats = set()
    for obj in keep_objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or id(mat) in seen_mats:
                continue
            if not _material_needs_basecolor_bake(mat):
                continue
            seen_mats.add(id(mat))
            jobs.append((obj, mat))

    if not jobs:
        return 0

    scene = bpy.context.scene
    prev_engine = scene.render.engine
    baked = 0

    for obj, mat in jobs:
        _ensure_mesh_uv(obj)

    try:
        _set_cycles_for_bake(scene)
        for obj, mat in jobs:
            try:
                if _bake_one_material_basecolor(obj, mat, size):
                    baked += 1
            except Exception:
                # 单个材质失败不阻断整资产；GLB 仍可导出（该材质可能仍偏色）。
                continue
    finally:
        try:
            scene.render.engine = prev_engine
        except Exception:
            pass
    return baked


def _bake_one_material_basecolor(obj, mat, size: int) -> bool:
    import bpy

    nt = mat.node_tree
    if nt is None:
        return False
    principled = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    output = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if principled is None or output is None:
        return False
    base_in = principled.inputs.get("Base Color")
    surface_in = output.inputs.get("Surface")
    if base_in is None or surface_in is None:
        return False

    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_render = False
    obj.hide_viewport = False
    try:
        obj.hide_set(False)
    except Exception:
        pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    img_name = f"DamBake_{mat.name}"[:55]
    # 同名残留先清掉，避免复用空图。
    old = bpy.data.images.get(img_name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(img_name, width=size, height=size, alpha=False)

    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.label = "DamBakeBaseColor"
    tex.location = (principled.location.x - 360, principled.location.y - 200)

    # Emission 烘焙：不受灯光影响，保留 ColorRamp/Wave 的纯色结果。
    saved_surface = [(lnk.from_socket, lnk.to_socket) for lnk in list(surface_in.links)]
    for lnk in list(surface_in.links):
        nt.links.remove(lnk)

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (output.location.x - 200, output.location.y)
    if base_in.is_linked:
        nt.links.new(base_in.links[0].from_socket, emit.inputs["Color"])
    else:
        emit.inputs["Color"].default_value = base_in.default_value
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(emit.outputs["Emission"], surface_in)

    for n in nt.nodes:
        n.select = False
    tex.select = True
    nt.nodes.active = tex

    bpy.ops.object.bake(type="EMIT")

    # 恢复 Surface → Principled，并把 Base Color 换成烘焙贴图。
    for lnk in list(surface_in.links):
        nt.links.remove(lnk)
    nt.nodes.remove(emit)
    for from_s, to_s in saved_surface:
        try:
            nt.links.new(from_s, to_s)
        except Exception:
            pass
    if not any(lnk.to_socket == surface_in for lnk in nt.links):
        nt.links.new(principled.outputs["BSDF"], surface_in)

    for lnk in list(base_in.links):
        nt.links.remove(lnk)
    nt.links.new(tex.outputs["Color"], base_in)

    try:
        img.pack()
    except Exception:
        pass
    return True


def export_glb(path: Path, keep_objects):
    import bpy
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in keep_objects:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
    if keep_objects:
        bpy.context.view_layer.objects.active = keep_objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        export_apply=True,
        use_selection=True,
    )


def main():
    args = _parse_args()
    if not args:
        print("missing job.json", file=sys.stderr)
        sys.exit(1)
    job_path = Path(args[0])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    result_path = Path(str(job_path) + ".result.json")

    try:
        import bpy
        src = Path(job["input"])
        if src.suffix.lower() == ".blend":
            open_blend(src)
        else:
            clear_default_scene()
            import_external(src)

        is_glb = src.suffix.lower() == ".glb"
        ext = src.suffix.lower()
        keep = prepare_asset_meshes(
            filter_blend_helpers=ext == ".blend",
            preserve_scene_lights=is_glb,
        )
        if not keep:
            raise RuntimeError("场景中没有可用的主体 MESH")

        center, radius, bounds = scene_bbox(keep)
        mins, maxs = bounds
        if center is None:
            raise RuntimeError("无法计算主体包围盒")

        cam, light = setup_camera_light(center, radius)
        cam.select_set(False)
        light.select_set(False)
        glb_out = Path(job["glb_out"])
        # GLB 原文件已由后端原样复制到 glb_out；不要经过 Blender 二次导出，
        # 否则可能丢失贴图、动画、扩展或灯光。
        if not job.get("preserve_source_glb", False):
            # BLEND：程序 Base Color 先烘成贴图，再 export_apply，供 Three 交互预览。
            baked_n = 0
            if ext == ".blend":
                baked_n = bake_blend_procedural_basecolors(keep, size=1024)
            export_glb(glb_out, keep)
        else:
            baked_n = 0
        if ext == ".blend":
            # 薄片类 BLEND（如蝴蝶）需要按包围盒最大面自动选正面。
            view_mins, view_maxs = mins, maxs
        else:
            # OBJ/FBX/GLTF 使用稳定的标准四视图，不受 BLEND 特例影响。
            view_mins, view_maxs = None, None

        # 固定图材质策略：
        # - GLB：始终原材质
        # - FBX/OBJ/BLEND：检测是否有贴图/非中性色等原材质 → 有则原材质，无则灰模
        # - GLTF：仍默认灰模缩略图（本次不改）
        if is_glb:
            use_original = True
        elif ext in (".fbx", ".obj", ".blend"):
            use_original = scene_has_original_materials(keep)
        else:
            use_original = False

        views = render_views(
            cam,
            center,
            radius,
            Path(job["views_dir"]),
            job["view_names"],
            view_mins,
            view_maxs,
            use_original_materials=use_original,
        )
        data = {
            "ok": True,
            "glb": str(glb_out),
            "views": views,
            "kept_objects": [o.name for o in keep],
            "center": [float(center.x), float(center.y), float(center.z)],
            "radius": float(radius),
            "has_original_materials": bool(use_original),
            "baked_basecolors": int(baked_n) if not job.get("preserve_source_glb", False) else 0,
            "error": None,
        }
    except Exception as e:
        data = {"ok": False, "glb": None, "views": [], "error": str(e)}

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DAM_RESULT", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
