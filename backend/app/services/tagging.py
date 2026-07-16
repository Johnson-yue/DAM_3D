"""自动打标：多视图图 → OpenRouter Gemini（不直接喂 3D 原件）。"""
from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Asset, Tag

logger = logging.getLogger(__name__)


def _b64_image(path: Path) -> dict:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
    }


def auto_tag_asset(db: Session, asset: Asset, view_paths: list[Path]) -> None:
    settings = get_settings()
    if not settings.auto_tag_enabled:
        asset.tag_status = "skipped"
        db.commit()
        return
    if not settings.openrouter_api_key.strip():
        asset.tag_status = "skipped"
        db.commit()
        return
    if not view_paths:
        asset.tag_status = "failed"
        asset.error_message = (asset.error_message or "") + ";无多视图可用于打标"
        db.commit()
        return

    content = [{"type": "text", "text": settings.auto_tag_prompt}]
    # 控制费用：最多送 4 张
    for p in view_paths[:4]:
        if p.exists():
            content.append(_b64_image(p))

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "DAM-3D-Render",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [{"role": "user", "content": content}],
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tags = _parse_tags(text)
        # 清除旧 auto 标签
        db.query(Tag).filter(Tag.asset_id == asset.id, Tag.source == "auto").delete()
        for t in tags:
            db.add(Tag(asset_id=asset.id, tag=t, source="auto"))
        asset.tag_status = "auto"
        db.commit()
    except Exception as e:
        logger.exception("auto tag failed for asset %s", asset.id)
        asset.tag_status = "failed"
        # 不阻断入库；只记错误
        asset.error_message = f"auto_tag: {e}"
        db.commit()


def _parse_tags(text: str) -> list[str]:
    raw = text.replace("，", ",").replace("、", ",").replace("\n", ",")
    parts = [p.strip(" #·•-") for p in raw.split(",")]
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 过长段落再按空格切
        if len(p) > 40:
            out.extend([x for x in p.split() if x])
        else:
            out.append(p)
    # 去重保序
    seen = set()
    uniq = []
    for t in out:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq[:20]
