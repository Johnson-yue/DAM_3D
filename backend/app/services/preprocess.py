"""预处理流水线：GLB + 多视图 + Embedding + 可选自动打标。"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import PREVIEW_WHITELIST, get_settings
from .. import db as dbmod
from ..db import Asset, Job, ViewEmbedding, init_db
from .blender_ops import run_blender_preprocess
from .embedding import embed_image, load_siglip
from .faiss_index import get_faiss_index
from .tagging import auto_tag_asset

logger = logging.getLogger(__name__)

_next_faiss_id_lock = threading.Lock()


def _alloc_faiss_ids(db: Session, n: int) -> list[int]:
    """分配全局唯一 faiss_id：取当前表最大值 + 1。"""
    with _next_faiss_id_lock:
        from sqlalchemy import func

        mx = db.query(func.max(ViewEmbedding.faiss_id)).scalar()
        start = 0 if mx is None else int(mx) + 1
        return list(range(start, start + n))


def process_asset(asset_id: int) -> None:
    init_db()
    # 必须通过模块属性取 SessionLocal，避免 import 时绑定到 None
    db = dbmod.SessionLocal()
    try:
        asset = db.get(Asset, asset_id)
        if not asset:
            return
        settings = get_settings()
        asset.status = "processing"
        db.commit()

        ext = asset.ext.lower()
        if ext not in PREVIEW_WHITELIST:
            asset.status = "preview_unsupported"
            asset.preview_supported = False
            db.commit()
            return

        glb_path = settings.glb_dir / f"{asset.id}.glb"
        views_dir = settings.views_dir / str(asset.id)

        db.add(Job(asset_id=asset.id, stage="glb_views", status="running"))
        db.commit()

        result = run_blender_preprocess(
            Path(asset.original_path),
            glb_path,
            views_dir,
            settings.view_count,
            preserve_source_glb=ext == ".glb",
        )
        if not result.get("ok"):
            asset.status = "failed"
            asset.error_message = result.get("error") or "Blender 失败"
            db.add(Job(asset_id=asset.id, stage="glb_views", status="failed", error=asset.error_message))
            db.commit()
            return

        asset.glb_path = str(glb_path)
        asset.preview_supported = True
        # 重处理成功后清除上一次失败留下的错误，避免 ready 状态仍显示旧报错。
        asset.error_message = None
        db.add(Job(asset_id=asset.id, stage="glb_views", status="done"))
        db.commit()

        # Embedding
        view_items = result.get("views") or []
        view_paths = [Path(v["path"]) for v in view_items]
        loaded = load_siglip(settings.siglip_path)
        if loaded and view_paths:
            # 删除旧向量
            old = db.query(ViewEmbedding).filter(ViewEmbedding.asset_id == asset.id).all()
            if old:
                get_faiss_index().remove_ids([o.faiss_id for o in old])
                for o in old:
                    db.delete(o)
                db.commit()

            ids = _alloc_faiss_ids(db, len(view_paths))
            index = get_faiss_index()
            for (vmeta, vpath, fid) in zip(view_items, view_paths, ids):
                try:
                    vec = embed_image(vpath)
                    index.add(vec, fid)
                    db.add(
                        ViewEmbedding(
                            asset_id=asset.id,
                            view_id=vmeta["view_id"],
                            image_path=str(vpath),
                            faiss_id=fid,
                            dim=int(vec.shape[0]),
                        )
                    )
                except Exception as e:
                    logger.exception("embed failed")
                    db.add(
                        Job(
                            asset_id=asset.id,
                            stage="embed",
                            status="failed",
                            error=str(e),
                        )
                    )
            db.commit()
        else:
            db.add(
                Job(
                    asset_id=asset.id,
                    stage="embed",
                    status="skipped",
                    error="SigLIP 未加载或无视图",
                )
            )
            db.commit()

        # 自动打标（失败不阻断）
        try:
            auto_tag_asset(db, asset, view_paths)
        except Exception as e:
            logger.exception("tag stage error")
            asset.tag_status = "failed"
            asset.error_message = f"tag: {e}"
            db.commit()

        asset.status = "ready"
        db.commit()
    except Exception as e:
        logger.exception("process_asset failed")
        try:
            asset = db.get(Asset, asset_id)
            if asset:
                asset.status = "failed"
                asset.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def enqueue_preprocess(asset_id: int) -> None:
    t = threading.Thread(target=process_asset, args=(asset_id,), daemon=True)
    t.start()
