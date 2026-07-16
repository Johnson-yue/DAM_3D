from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    id: int
    tag: str
    source: str

    class Config:
        from_attributes = True


class ViewOut(BaseModel):
    id: int
    view_id: str
    image_path: str
    faiss_id: int

    class Config:
        from_attributes = True


class AssetOut(BaseModel):
    id: int
    name: str
    original_path: str
    source_path: Optional[str] = None
    ext: str
    status: str
    preview_supported: bool
    glb_path: Optional[str] = None
    tag_status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = []
    views: list[ViewOut] = []
    best_view_url: Optional[str] = None

    class Config:
        from_attributes = True


class ScanRequest(BaseModel):
    directory: str
    recursive: bool = True


class TagsUpdate(BaseModel):
    tags: list[str]


class SettingsOut(BaseModel):
    library_root: str
    blender_exe: str
    siglip_path: str
    openrouter_api_key_set: bool
    openrouter_model: str
    auto_tag_enabled: bool
    auto_tag_prompt: str
    top_k: int
    view_count: int
    search_alpha: float
    search_beta: float
    faiss_recall_n: int


class SettingsUpdate(BaseModel):
    library_root: Optional[str] = None
    blender_exe: Optional[str] = None
    siglip_path: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    auto_tag_enabled: Optional[bool] = None
    auto_tag_prompt: Optional[str] = None
    top_k: Optional[int] = None
    view_count: Optional[int] = None
    search_alpha: Optional[float] = None
    search_beta: Optional[float] = None
    faiss_recall_n: Optional[int] = None


class SearchHit(BaseModel):
    asset: AssetOut
    score: float
    best_view_id: str
    best_view_url: str
    visual_sim: float
    tag_match: float


class SearchResponse(BaseModel):
    top1: Optional[SearchHit] = None
    others: list[SearchHit] = []
    k: int


class AnnotationIn(BaseModel):
    type: str
    geometry: dict[str, Any]
    camera_snapshot: Optional[dict[str, Any]] = None


class AnnotationOut(BaseModel):
    id: int
    asset_id: int
    type: str
    geometry: dict[str, Any]
    camera_snapshot: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class AnnotationsReplace(BaseModel):
    items: list[AnnotationIn] = Field(default_factory=list)
