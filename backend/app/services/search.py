"""检索：视图级 faiss → 按资产 Max 聚合 → 可选标签加权。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..db import Asset, ViewEmbedding
from ..schemas import AssetOut, SearchHit, SearchResponse, TagOut, ViewOut
from .embedding import embed_pil, embed_text
from .faiss_index import get_faiss_index


def _asset_to_out(asset: Asset, best_view_url: str | None = None) -> AssetOut:
    return AssetOut(
        id=asset.id,
        name=asset.name,
        original_path=asset.original_path,
        source_path=asset.source_path,
        ext=asset.ext,
        status=asset.status,
        preview_supported=asset.preview_supported,
        glb_path=asset.glb_path,
        tag_status=asset.tag_status,
        error_message=asset.error_message,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        tags=[TagOut.model_validate(t) for t in asset.tags],
        views=[ViewOut.model_validate(v) for v in asset.views],
        best_view_url=best_view_url,
    )


def _tag_match(query: str, asset: Asset) -> float:
    if not query.strip() or not asset.tags:
        return 0.0
    q = query.lower()
    tags = [t.tag.lower() for t in asset.tags]
    # 完全命中 / 子串命中
    score = 0.0
    for t in tags:
        if t == q or q == t:
            score = max(score, 1.0)
        elif t in q or q in t:
            score = max(score, 0.7)
        else:
            # token overlap
            qt = set(q.replace(",", " ").split())
            tt = set(t.replace(",", " ").split())
            if qt & tt:
                score = max(score, 0.4)
    return score


def search_by_vector(
    db: Session,
    query_vec: np.ndarray,
    text_for_tags: str | None = None,
    apply_tag_boost: bool = False,
) -> SearchResponse:
    settings = get_settings()
    index = get_faiss_index()
    hits = index.search(query_vec, settings.faiss_recall_n)

    # faiss_id -> view row
    if not hits:
        return SearchResponse(top1=None, others=[], k=settings.top_k)

    id_to_score = {fid: score for fid, score in hits}
    views = (
        db.query(ViewEmbedding)
        .filter(ViewEmbedding.faiss_id.in_(list(id_to_score.keys())))
        .all()
    )
    # 按资产 Max 聚合
    best: dict[int, tuple[float, ViewEmbedding]] = {}
    for v in views:
        s = id_to_score.get(v.faiss_id, -1e9)
        if v.asset_id not in best or s > best[v.asset_id][0]:
            best[v.asset_id] = (s, v)

    asset_ids = list(best.keys())
    assets = (
        db.query(Asset)
        .options(joinedload(Asset.tags), joinedload(Asset.views))
        .filter(Asset.id.in_(asset_ids))
        .all()
    )
    asset_map = {a.id: a for a in assets}

    ranked: list[SearchHit] = []
    alpha, beta = settings.search_alpha, settings.search_beta
    for aid, (visual, view) in best.items():
        asset = asset_map.get(aid)
        if not asset:
            continue
        tag_m = 0.0
        if apply_tag_boost and text_for_tags:
            tag_m = _tag_match(text_for_tags, asset)
            final = alpha * float(visual) + beta * tag_m
        else:
            final = float(visual)
        url = f"/media/views/{aid}/{Path(view.image_path).name}"
        ranked.append(
            SearchHit(
                asset=_asset_to_out(asset, best_view_url=url),
                score=final,
                best_view_id=view.view_id,
                best_view_url=url,
                visual_sim=float(visual),
                tag_match=tag_m,
            )
        )

    ranked.sort(key=lambda x: x.score, reverse=True)
    k = settings.top_k
    ranked = ranked[:k]
    top1 = ranked[0] if ranked else None
    others = ranked[1:] if len(ranked) > 1 else []
    return SearchResponse(top1=top1, others=others, k=k)


def search_text(db: Session, query: str) -> SearchResponse:
    vec = embed_text(query)
    return search_by_vector(db, vec, text_for_tags=query, apply_tag_boost=True)


def search_image(db: Session, image: Image.Image) -> SearchResponse:
    vec = embed_pil(image)
    return search_by_vector(db, vec, apply_tag_boost=False)
