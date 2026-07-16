from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings, save_settings
from ..schemas import SettingsOut, SettingsUpdate
from ..services.embedding import embedding_status

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_cfg():
    s = get_settings()
    return SettingsOut(
        library_root=str(s.library_root),
        blender_exe=str(s.blender_exe),
        siglip_path=str(s.siglip_path),
        openrouter_api_key_set=bool(s.openrouter_api_key.strip()),
        openrouter_model=s.openrouter_model,
        auto_tag_enabled=s.auto_tag_enabled,
        auto_tag_prompt=s.auto_tag_prompt,
        top_k=s.top_k,
        view_count=s.view_count,
        search_alpha=s.search_alpha,
        search_beta=s.search_beta,
        faiss_recall_n=s.faiss_recall_n,
    )


@router.put("", response_model=SettingsOut)
def put_cfg(body: SettingsUpdate):
    data = body.model_dump(exclude_none=True)
    save_settings(data)
    return get_cfg()


@router.get("/status")
def status():
    s = get_settings()
    return {
        "embedding": embedding_status(),
        "blender_exists": s.blender_exe.exists(),
        "library_root": str(s.library_root),
        "siglip_path": str(s.siglip_path),
    }
