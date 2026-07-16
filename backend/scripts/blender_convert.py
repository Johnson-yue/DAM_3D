"""
Blender 后台脚本：由 blender --python 调用。
用法: blender --background --python blender_convert.py -- job.json

.blend 使用 open_mainfile；主体按面数优先选取，剔除背景平面等辅助体。
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


def prepare_asset_meshes(filter_blend_helpers=False, preserve_scene_lights=False):
    """
    准备参与导出和渲染的网格。

    OBJ / FBX / GLTF：保留全部网格。此类交换格式通常会把一个完整资产拆成
    大量独立小部件，不能按面数删除。

    BLEND：才执行主体筛选，排除工作场景中的背景平面、灯光和辅助对象。
    """
    import bpy

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
        # 该规则只适用于原始工作场景 .blend，绝不用于 OBJ/FBX。
        for obj in list(meshes):
            name = obj.name.lower()
            if "平面" in obj.name or "plane" in name or _is_thin_plane(obj):
                if _mesh_poly_count(obj) <= 2 or _is_thin_plane(obj):
                    bpy.data.objects.remove(obj, do_unlink=True)

        meshes = [
            obj
            for obj in bpy.context.scene.objects
            if obj.type == "MESH" and obj.name in view_layer_names
        ]
        if not meshes:
            return []

        ranked = sorted(meshes, key=_mesh_poly_count, reverse=True)
        top = _mesh_poly_count(ranked[0])
        keep = [
            obj
            for obj in ranked
            if _mesh_poly_count(obj) > 0
            and (_mesh_poly_count(obj) >= max(1, int(top * 0.3)) or obj == ranked[0])
        ]
        keep_set = set(keep)
        for obj in list(bpy.context.scene.objects):
            if obj.type == "MESH" and obj not in keep_set:
                bpy.data.objects.remove(obj, do_unlink=True)
    else:
        # 交换格式可能包含成百上千个不同大小的零件，全部保留。
        keep = [obj for obj in meshes if _mesh_poly_count(obj) > 0]

    for obj in bpy.context.scene.objects:
        if obj.name not in view_layer_names:
            continue
        if obj.type != "MESH" and not (preserve_scene_lights and obj.type == "LIGHT"):
            obj.hide_render = True
            obj.hide_viewport = True

    # 取消隐藏主体，应用可视变换
    bpy.ops.object.select_all(action="DESELECT")
    for obj in keep:
        if obj.name not in view_layer_names:
            continue
        obj.hide_render = False
        obj.hide_viewport = False
        obj.hide_set(False)
        obj.select_set(True)
    if keep:
        bpy.context.view_layer.objects.active = keep[0]
        try:
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        except Exception:
            pass
    return keep


def scene_bbox(objects):
    from mathutils import Vector
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    has = False
    for obj in objects:
        if obj.type != "MESH":
            continue
        has = True
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
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
    """按包围盒自动生成视角：front=看向面积最大的那一面（避免蝴蝶被拍成侧棱）。"""
    from mathutils import Vector
    size = maxs - mins
    # 各轴作为视线方向时，看见的是另外两轴张成的面
    faces = [
        ("x", size.y * size.z, Vector((1, 0, 0.25))),
        ("y", size.x * size.z, Vector((0, 1, 0.25))),
        ("z", size.x * size.y, Vector((0.25, 0.25, 1))),
    ]
    faces.sort(key=lambda x: x[1], reverse=True)
    primary = faces[0][2].normalized()
    secondary = faces[1][2].normalized()
    tertiary = faces[2][2].normalized()
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
        # GLB 专用：使用原始 PBR 材质/内嵌贴图，不走其他格式的灰模分支。
        try:
            scene.render.engine = "BLENDER_EEVEE"
        except Exception:
            scene.render.engine = "CYCLES"
        scene.world.use_nodes = True
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.06, 0.075, 0.095, 1.0)
            background.inputs["Strength"].default_value = 0.45
        scene.view_settings.look = "AgX - Medium High Contrast"
        scene.view_settings.exposure = 1.0
    else:
        # OBJ/FBX/BLEND 的稳定灰模缩略图逻辑保持不变。
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
            try:
                scene.render.engine = "BLENDER_EEVEE"
            except Exception:
                scene.render.engine = "CYCLES"

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
        keep = prepare_asset_meshes(
            filter_blend_helpers=src.suffix.lower() == ".blend",
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
            export_glb(glb_out, keep)
        if src.suffix.lower() == ".blend":
            # 薄片类 BLEND（如蝴蝶）需要按包围盒最大面自动选正面。
            view_mins, view_maxs = mins, maxs
        else:
            # OBJ/FBX/GLTF 使用稳定的标准四视图，不受 BLEND 特例影响。
            view_mins, view_maxs = None, None
        views = render_views(
            cam,
            center,
            radius,
            Path(job["views_dir"]),
            job["view_names"],
            view_mins,
            view_maxs,
            use_original_materials=is_glb,
        )
        data = {
            "ok": True,
            "glb": str(glb_out),
            "views": views,
            "kept_objects": [o.name for o in keep],
            "center": [float(center.x), float(center.y), float(center.z)],
            "radius": float(radius),
            "error": None,
        }
    except Exception as e:
        data = {"ok": False, "glb": None, "views": [], "error": str(e)}

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DAM_RESULT", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
