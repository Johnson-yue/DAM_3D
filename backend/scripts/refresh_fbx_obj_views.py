"""刷新库中 FBX/OBJ 的固定多视图（按是否含原材质渲染），并重建 embedding。

用法（backend 目录）:
  python scripts/refresh_fbx_obj_views.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db as dbmod
from app.config import load_settings
from app.db import Asset, init_db
from app.services.preprocess import process_asset


def main() -> None:
    load_settings()
    init_db()
    db = dbmod.SessionLocal()
    try:
        rows = (
            db.query(Asset)
            .filter(Asset.ext.in_([".fbx", ".FBX", ".obj", ".OBJ"]))
            .order_by(Asset.id.asc())
            .all()
        )
        ids = [a.id for a in rows]
        names = [(a.id, a.name, a.ext, a.status) for a in rows]
    finally:
        db.close()

    print(f"refreshing {len(ids)} FBX/OBJ assets")
    for item in names:
        print(" -", item)
    for aid in ids:
        print(f"process asset {aid} …")
        process_asset(aid)
        print(f"done asset {aid}")
    print("all done")


if __name__ == "__main__":
    main()
