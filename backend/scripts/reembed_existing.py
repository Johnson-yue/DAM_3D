"""一次性：为已有多视图重新写入 SigLIP embedding + faiss，并标记 ready。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings, get_settings
from app import db as dbmod
from app.db import init_db, Asset, ViewEmbedding
from app.services.embedding import load_siglip, embed_image
from app.services.faiss_index import reset_faiss_index


def main():
    load_settings()
    init_db()
    settings = get_settings()
    assert load_siglip(settings.siglip_path), "siglip load failed"

    idx_path = settings.faiss_dir / "views.index"
    if idx_path.exists():
        idx_path.unlink()
    index = reset_faiss_index()

    db = dbmod.SessionLocal()
    db.query(ViewEmbedding).delete()
    db.commit()

    assets = db.query(Asset).all()
    next_id = 0
    for asset in assets:
        views_dir = settings.views_dir / str(asset.id)
        glb = settings.glb_dir / f"{asset.id}.glb"
        if not views_dir.exists():
            print("skip no views", asset.id)
            continue
        for png in sorted(views_dir.glob("*.png")):
            vec = embed_image(png)
            print(asset.id, png.name, vec.shape)
            index.add(vec, next_id)
            db.add(
                ViewEmbedding(
                    asset_id=asset.id,
                    view_id=png.stem,
                    image_path=str(png),
                    faiss_id=next_id,
                    dim=int(vec.shape[0]),
                )
            )
            next_id += 1
        if glb.exists():
            asset.glb_path = str(glb)
            asset.preview_supported = True
            asset.status = "ready"
            asset.error_message = None
        db.commit()
        print("ready", asset.id, asset.name)

    print("ntotal", index.ntotal)
    db.close()


if __name__ == "__main__":
    main()
