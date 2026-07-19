"""按新 BLEND 主体规则刷新库内已有 .blend（GLB + 固定图 + embedding）。

用法（backend 目录）:
  python scripts/refresh_blend_views.py
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
            .filter(Asset.ext.in_([".blend", ".BLEND"]))
            .order_by(Asset.id.asc())
            .all()
        )
        ids = [a.id for a in rows]
        names = [(a.id, a.name, a.status) for a in rows]
    finally:
        db.close()

    print(f"refreshing {len(ids)} BLEND assets")
    for item in names:
        print(" -", item)
    for aid in ids:
        print(f"process asset {aid} …")
        process_asset(aid)
        print(f"done asset {aid}")
    print("all done")


if __name__ == "__main__":
    main()
