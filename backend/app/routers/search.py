from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SearchResponse
from ..services.search import search_image, search_text

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/text", response_model=SearchResponse)
def search_by_text(q: str = Form(...), db: Session = Depends(get_db)):
    return search_text(db, q)


@router.post("/image", response_model=SearchResponse)
async def search_by_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    img = Image.open(file.file)
    return search_image(db, img)
