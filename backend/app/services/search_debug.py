"""检索 Debug：向 faiss 注入随机噪声向量，并支持 hit@K 基准与启动清残留。"""
from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import ViewEmbedding
from .embedding import embed_image
from .faiss_index import get_faiss_index
from .search import search_by_vector

logger = logging.getLogger(__name__)

# 预留外部 ID 段，避免与正式 view_embeddings.faiss_id（通常从 0 递增）冲突。
DEBUG_ID_BASE = 1_000_000_000
MAX_N = 5000
DEFAULT_N = 100
DEFAULT_M = 20


def _probe_path() -> Path:
    return get_settings().faiss_dir / "debug_probe_ids.json"


def _read_state() -> dict:
    path = _probe_path()
    if not path.exists():
        return {"enabled": False, "n": 0, "ids": [], "dim": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "enabled": bool(data.get("enabled")),
            "n": int(data.get("n") or 0),
            "ids": [int(x) for x in (data.get("ids") or [])],
            "dim": data.get("dim"),
        }
    except Exception:
        return {"enabled": False, "n": 0, "ids": [], "dim": None}


def _write_state(state: dict) -> None:
    path = _probe_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_debug_vectors() -> dict:
    """删除已登记的 Debug 噪声向量；用于关 Debug 与启动清残留。"""
    state = _read_state()
    ids = state.get("ids") or []
    removed = 0
    if ids:
        try:
            get_faiss_index().remove_ids(ids)
            removed = len(ids)
        except Exception:
            logger.exception("remove debug vectors failed")
    empty = {"enabled": False, "n": 0, "ids": [], "dim": None}
    _write_state(empty)
    index = get_faiss_index()
    return {
        "ok": True,
        "removed": removed,
        "enabled": False,
        "n": 0,
        "ntotal": index.ntotal,
        "dim": index.dim,
    }


def debug_status() -> dict:
    state = _read_state()
    index = get_faiss_index()
    return {
        "enabled": bool(state.get("enabled")),
        "n": int(state.get("n") or 0),
        "ids_count": len(state.get("ids") or []),
        "ntotal": index.ntotal,
        "dim": index.dim,
        "max_n": MAX_N,
        "default_n": DEFAULT_N,
        "default_m": DEFAULT_M,
    }


def enable_debug(n: int) -> dict:
    """先清残留，再注入 N 条与正式索引同维的随机归一化向量。"""
    n = int(n)
    if n < 1 or n > MAX_N:
        raise ValueError(f"N 须在 1–{MAX_N} 之间")

    cleanup_debug_vectors()
    index = get_faiss_index()
    if index.index is None or index.dim is None or index.ntotal <= 0:
        raise RuntimeError("faiss 索引为空或维度未知，请先完成至少一条资产的 Embedding")

    dim = int(index.dim)
    rng = np.random.default_rng()
    vectors = rng.standard_normal((n, dim), dtype=np.float32)
    ids = list(range(DEBUG_ID_BASE, DEBUG_ID_BASE + n))
    index.add_batch(vectors, ids)
    state = {"enabled": True, "n": n, "ids": ids, "dim": dim}
    _write_state(state)
    return {
        "ok": True,
        "enabled": True,
        "n": n,
        "ntotal": index.ntotal,
        "dim": dim,
    }


def disable_debug() -> dict:
    return cleanup_debug_vectors()


def run_benchmark(db: Session, m: int) -> dict:
    """
    随机抽最多 M 条真实视图：用图像塔重编码后检索，
    统计耗时与 hit@K（Top-K 资产列表是否含该视图所属资产）。
    """
    m = int(m)
    if m < 1:
        raise ValueError("M 须 ≥ 1")
    settings = get_settings()
    k = settings.top_k
    views = db.query(ViewEmbedding).all()
    if not views:
        raise RuntimeError("没有可用于探针的真实视图向量")

    sample = views if len(views) <= m else random.sample(views, m)
    elapsed: list[float] = []
    hits = 0
    details = []

    for view in sample:
        path = Path(view.image_path)
        if not path.exists():
            details.append(
                {
                    "asset_id": view.asset_id,
                    "view_id": view.view_id,
                    "ok": False,
                    "error": "image missing",
                }
            )
            continue
        t0 = time.perf_counter()
        vec = embed_image(path)
        resp = search_by_vector(db, vec, apply_tag_boost=False)
        ms = (time.perf_counter() - t0) * 1000.0
        elapsed.append(ms)
        ranked_ids = []
        if resp.top1:
            ranked_ids.append(resp.top1.asset.id)
        ranked_ids.extend(h.asset.id for h in resp.others)
        hit = view.asset_id in ranked_ids[:k]
        if hit:
            hits += 1
        details.append(
            {
                "asset_id": view.asset_id,
                "view_id": view.view_id,
                "ok": True,
                "hit": hit,
                "elapsed_ms": round(ms, 3),
            }
        )

    probed = len(elapsed)
    elapsed_sorted = sorted(elapsed)
    median = elapsed_sorted[len(elapsed_sorted) // 2] if elapsed_sorted else None
    mean = (sum(elapsed) / probed) if probed else None
    state = _read_state()
    index = get_faiss_index()
    return {
        "ok": True,
        "m_requested": m,
        "probed": probed,
        "k": k,
        "hit_at_k": (hits / probed) if probed else 0.0,
        "hits": hits,
        "elapsed_ms_mean": round(mean, 3) if mean is not None else None,
        "elapsed_ms_median": round(median, 3) if median is not None else None,
        "elapsed_ms_min": round(min(elapsed), 3) if elapsed else None,
        "elapsed_ms_max": round(max(elapsed), 3) if elapsed else None,
        "debug_enabled": bool(state.get("enabled")),
        "noise_n": int(state.get("n") or 0),
        "ntotal": index.ntotal,
        "details": details,
    }
