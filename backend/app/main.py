from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings, load_settings
from .db import init_db
from .routers import assets, search, settings as settings_router
from .services.embedding import load_siglip
from .services.faiss_index import get_faiss_index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dam")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_settings()
    init_db()
    settings = get_settings()
    # 尝试加载模型；失败不阻断启动
    load_siglip(settings.siglip_path)
    get_faiss_index()
    yield


app = FastAPI(title="DAM 3D Render", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(search.router)
app.include_router(settings_router.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/media/views/{asset_id}/{filename}")
def media_view(asset_id: int, filename: str):
    settings = get_settings()
    path = settings.views_dir / str(asset_id) / filename
    if not path.exists():
        return {"error": "not found"}
    return FileResponse(path)


# 可选：挂载前端构建产物
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
