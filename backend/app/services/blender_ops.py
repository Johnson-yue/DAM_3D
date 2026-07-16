"""Blender 无头：导入原件 → 导出 GLB + 多视图渲染。"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import get_settings, view_names_for_count

logger = logging.getLogger(__name__)

BLENDER_WORKER = Path(__file__).resolve().parents[2] / "scripts" / "blender_convert.py"


def run_blender_preprocess(
    original_path: Path,
    glb_out: Path,
    views_dir: Path,
    view_count: int,
    preserve_source_glb: bool = False,
) -> dict:
    """
    调用本机 Blender 执行 worker 脚本。
    返回 dict: {ok, glb, views: [{view_id, path}], error?}
    """
    settings = get_settings()
    blender = settings.blender_exe
    if not blender.exists():
        return {"ok": False, "error": f"Blender 不存在: {blender}", "views": []}

    views_dir.mkdir(parents=True, exist_ok=True)
    glb_out.parent.mkdir(parents=True, exist_ok=True)
    names = view_names_for_count(view_count)

    # GLB 已经是浏览器原生格式。直接复制原文件，完整保留内嵌材质、贴图、
    # 动画及 KHR_lights_punctual；Blender 仅用于生成多视图缩略图。
    if preserve_source_glb:
        shutil.copy2(original_path, glb_out)

    job = {
        "input": str(original_path),
        "glb_out": str(glb_out),
        "views_dir": str(views_dir),
        "view_names": names,
        "preserve_source_glb": preserve_source_glb,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(job, f, ensure_ascii=False)
        job_path = Path(f.name)

    cmd = [
        str(blender),
        "--background",
        "--python",
        str(BLENDER_WORKER),
        "--",
        str(job_path),
    ]
    logger.info("Running Blender: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Blender 超时", "views": []}
    finally:
        try:
            job_path.unlink(missing_ok=True)
        except Exception:
            pass

    result_path = Path(str(job_path) + ".result.json")
    # worker 把结果写到 job_path.result.json；若没有则从 stdout 找
    if result_path.exists():
        data = json.loads(result_path.read_text(encoding="utf-8"))
        try:
            result_path.unlink(missing_ok=True)
        except Exception:
            pass
        return data

    # 回退：检查产物是否存在
    views = []
    for name in names:
        p = views_dir / f"{name}.png"
        if p.exists():
            views.append({"view_id": name, "path": str(p)})
    ok = glb_out.exists() and len(views) > 0
    err = None if ok else (proc.stderr[-2000:] if proc.stderr else "Blender 未生成产物")
    return {"ok": ok, "glb": str(glb_out) if glb_out.exists() else None, "views": views, "error": err}
