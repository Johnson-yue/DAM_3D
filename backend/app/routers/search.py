from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import DebugBenchmarkRequest, DebugEnableRequest, SearchResponse
from ..services.search import search_image, search_text
from ..services import search_debug

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/text", response_model=SearchResponse)
def search_by_text(q: str = Form(...), db: Session = Depends(get_db)):
    return search_text(db, q)


@router.post("/image", response_model=SearchResponse)
async def search_by_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    img = Image.open(file.file)
    return search_image(db, img)


@router.get("/debug/status")
def get_debug_status():
    return search_debug.debug_status()


@router.post("/debug/enable")
def enable_search_debug(body: DebugEnableRequest):
    try:
        return search_debug.enable_debug(body.n)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/debug/disable")
def disable_search_debug():
    return search_debug.disable_debug()


@router.post("/debug/benchmark")
def benchmark_search_debug(body: DebugBenchmarkRequest, db: Session = Depends(get_db)):
    try:
        return search_debug.run_benchmark(db, body.m)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
