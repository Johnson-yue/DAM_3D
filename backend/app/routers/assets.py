from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..db import Annotation, Asset, Job, Tag, ViewEmbedding, get_db
from ..schemas import (
    AnnotationOut,
    AnnotationsReplace,
    AssetOut,
    ScanRequest,
    TagOut,
    TagsUpdate,
    ViewOut,
)
from ..services.ingest import copy_into_library, scan_directory
from ..services.faiss_index import get_faiss_index
from ..services.preprocess import enqueue_preprocess, process_asset
from ..services.tagging import auto_tag_asset

router = APIRouter(prefix="/api/assets", tags=["assets"])


def serialize_asset(a: Asset) -> AssetOut:
    best = None
    if a.views:
        # 资产卡片固定优先展示自动取景后的 front，避免数据库关系顺序
        # 恰好返回 back/left，导致缩略图角度不稳定。
        v0 = next((view for view in a.views if view.view_id == "front"), a.views[0])
        best = f"/media/views/{a.id}/{Path(v0.image_path).name}"
    return AssetOut(
        id=a.id,
        name=a.name,
        original_path=a.original_path,
        source_path=a.source_path,
        ext=a.ext,
        status=a.status,
        preview_supported=a.preview_supported,
        glb_path=a.glb_path,
        tag_status=a.tag_status,
        error_message=a.error_message,
        created_at=a.created_at,
        updated_at=a.updated_at,
        tags=[TagOut.model_validate(t) for t in a.tags],
        views=[ViewOut.model_validate(v) for v in a.views],
        best_view_url=best,
    )


@router.get("")
def list_assets(db: Session = Depends(get_db)) -> list[AssetOut]:
    rows = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .order_by(Asset.id.desc())
        .all()
    )
    return [serialize_asset(a) for a in rows]


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)) -> AssetOut:
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset_id)
        .first()
    )
    if not a:
        raise HTTPException(404, "asset not found")
    return serialize_asset(a)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    """删除资产记录、向量以及托管库内原件/衍生品。"""
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "asset not found")

    settings = get_settings()
    views = db.query(ViewEmbedding).filter(ViewEmbedding.asset_id == asset_id).all()
    if views:
        get_faiss_index().remove_ids([view.faiss_id for view in views])

    db.query(Job).filter(Job.asset_id == asset_id).delete()
    db.query(Annotation).filter(Annotation.asset_id == asset_id).delete()
    db.query(Tag).filter(Tag.asset_id == asset_id).delete()
    db.query(ViewEmbedding).filter(ViewEmbedding.asset_id == asset_id).delete()
    db.delete(a)
    db.commit()

    # 只删除托管库中的副本与衍生品，不触碰 source_path。
    shutil.rmtree(settings.originals_dir / str(asset_id), ignore_errors=True)
    shutil.rmtree(settings.views_dir / str(asset_id), ignore_errors=True)
    (settings.glb_dir / f"{asset_id}.glb").unlink(missing_ok=True)
    (settings.annotations_dir / f"{asset_id}.json").unlink(missing_ok=True)
    return {"ok": True, "deleted_asset_id": asset_id}


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AssetOut:
    settings = get_settings()
    tmp = settings.library_root / "_upload_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / (file.filename or "upload.bin")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    asset = copy_into_library(dest, db, source_path=None)
    try:
        dest.unlink(missing_ok=True)
    except Exception:
        pass
    enqueue_preprocess(asset.id)
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset.id)
        .first()
    )
    return serialize_asset(a)


@router.post("/scan")
def scan_assets(body: ScanRequest, db: Session = Depends(get_db)) -> list[AssetOut]:
    assets = scan_directory(body.directory, db, recursive=body.recursive)
    for a in assets:
        if a.status in ("copied", "failed"):
            enqueue_preprocess(a.id)
    # re-fetch
    ids = [a.id for a in assets]
    rows = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id.in_(ids))
        .all()
    )
    return [serialize_asset(a) for a in rows]


@router.post("/{asset_id}/reprocess")
def reprocess(asset_id: int, db: Session = Depends(get_db)) -> AssetOut:
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    enqueue_preprocess(asset_id)
    return serialize_asset(a)


@router.put("/{asset_id}/tags")
def update_tags(asset_id: int, body: TagsUpdate, db: Session = Depends(get_db)) -> AssetOut:
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset_id)
        .first()
    )
    if not a:
        raise HTTPException(404)
    db.query(Tag).filter(Tag.asset_id == asset_id, Tag.source == "user").delete()
    for t in body.tags:
        t = t.strip()
        if t:
            db.add(Tag(asset_id=asset_id, tag=t, source="user"))
    if body.tags:
        a.tag_status = "manual" if a.tag_status != "auto" else a.tag_status
    db.commit()
    db.refresh(a)
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset_id)
        .first()
    )
    return serialize_asset(a)


@router.post("/{asset_id}/auto-tag")
def retry_auto_tag(asset_id: int, db: Session = Depends(get_db)) -> AssetOut:
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset_id)
        .first()
    )
    if not a:
        raise HTTPException(404)
    paths = [Path(v.image_path) for v in a.views]
    auto_tag_asset(db, a, paths)
    a = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id == asset_id)
        .first()
    )
    return serialize_asset(a)


@router.get("/{asset_id}/annotations")
def list_annotations(asset_id: int, db: Session = Depends(get_db)) -> list[AnnotationOut]:
    rows = db.query(Annotation).filter(Annotation.asset_id == asset_id).all()
    out = []
    for r in rows:
        out.append(
            AnnotationOut(
                id=r.id,
                asset_id=r.asset_id,
                type=r.type,
                geometry=json.loads(r.geometry_json),
                camera_snapshot=json.loads(r.camera_snapshot) if r.camera_snapshot else None,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


@router.put("/{asset_id}/annotations")
def replace_annotations(
    asset_id: int, body: AnnotationsReplace, db: Session = Depends(get_db)
) -> list[AnnotationOut]:
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    db.query(Annotation).filter(Annotation.asset_id == asset_id).delete()
    for item in body.items:
        db.add(
            Annotation(
                asset_id=asset_id,
                type=item.type,
                geometry_json=json.dumps(item.geometry, ensure_ascii=False),
                camera_snapshot=json.dumps(item.camera_snapshot, ensure_ascii=False)
                if item.camera_snapshot
                else None,
            )
        )
    db.commit()
    # 同步写一份 JSON 到 annotations 目录便于导出/备份
    settings = get_settings()
    ann_path = settings.annotations_dir / f"{asset_id}.json"
    payload = [i.model_dump() for i in body.items]
    ann_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return list_annotations(asset_id, db)


@router.get("/{asset_id}/glb")
def get_glb(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a or not a.glb_path or not Path(a.glb_path).exists():
        raise HTTPException(404, "glb not ready")
    return FileResponse(a.glb_path, media_type="model/gltf-binary", filename=f"{asset_id}.glb")
