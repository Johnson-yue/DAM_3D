"""入库：复制原件到托管库（不改写源文件）。"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import PREVIEW_WHITELIST, get_settings
from ..db import Asset


def file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    h.update(str(path.resolve()).encode("utf-8"))
    st = path.stat()
    h.update(str(st.st_size).encode())
    h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()[:16]


def copy_into_library(src: Path, db: Session, source_path: str | None = None) -> Asset:
    settings = get_settings()
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(str(src))

    ext = src.suffix.lower()
    # 增量：同源路径+指纹已存在则跳过（简化：按 source_path + name）
    if source_path:
        existing = (
            db.query(Asset)
            .filter(Asset.source_path == str(Path(source_path).resolve()), Asset.name == src.name)
            .first()
        )
        if existing:
            return existing

    asset = Asset(
        name=src.name,
        original_path="",  # 稍后填
        source_path=str(Path(source_path).resolve()) if source_path else None,
        ext=ext,
        status="copied",
        preview_supported=ext in PREVIEW_WHITELIST,
        tag_status="none",
    )
    db.add(asset)
    db.flush()  # 拿到 id

    dest_dir = settings.originals_dir / str(asset.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)  # 复制，不移动、不改写源

    asset.original_path = str(dest)
    db.commit()
    db.refresh(asset)
    return asset


def scan_directory(directory: str, db: Session, recursive: bool = True) -> list[Asset]:
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(directory)
    pattern = "**/*" if recursive else "*"
    assets: list[Asset] = []
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        # 跳过隐藏/临时
        if path.name.startswith("."):
            continue
        assets.append(copy_into_library(path, db, source_path=str(path)))
    return assets
