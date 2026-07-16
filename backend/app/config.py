"""应用配置：路径、检索与打标参数均可覆盖。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：.../DAM_3D_Render
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "backend" / "config.local.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DAM_", extra="ignore")

    library_root: Path = Path(r"E:\code\Data\DAM_Library")
    blender_exe: Path = Path(
        r"D:\Program Files (x86)\Blender Foundation\Blender 5.0\blender.exe"
    )
    siglip_path: Path = Path(r"E:\Weights\VLM\siglip2-so400m-patch16-512")
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-3-pro-preview"
    auto_tag_enabled: bool = True
    auto_tag_prompt: str = "使用短词描述这个游戏资产"
    top_k: int = 10
    view_count: int = 4
    search_alpha: float = 0.7  # 视觉权重
    search_beta: float = 0.3  # 标签权重
    faiss_recall_n: int = 50
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def originals_dir(self) -> Path:
        return self.library_root / "originals"

    @property
    def glb_dir(self) -> Path:
        return self.library_root / "previews" / "glb"

    @property
    def views_dir(self) -> Path:
        return self.library_root / "previews" / "views"

    @property
    def embeddings_dir(self) -> Path:
        return self.library_root / "embeddings"

    @property
    def annotations_dir(self) -> Path:
        return self.library_root / "annotations"

    @property
    def faiss_dir(self) -> Path:
        return self.library_root / "faiss"

    @property
    def db_path(self) -> Path:
        return self.library_root / "dam.sqlite3"


_settings: Settings | None = None


def ensure_library_dirs(settings: Settings) -> None:
    for d in (
        settings.library_root,
        settings.originals_dir,
        settings.glb_dir,
        settings.views_dir,
        settings.embeddings_dir,
        settings.annotations_dir,
        settings.faiss_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: Path | None = None) -> Settings:
    global _settings
    path = config_path or DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    settings = Settings(**data)
    ensure_library_dirs(settings)
    _settings = settings
    return settings


def get_settings() -> Settings:
    if _settings is None:
        return load_settings()
    return _settings


def save_settings(updates: dict[str, Any], config_path: Path | None = None) -> Settings:
    path = config_path or DEFAULT_CONFIG_PATH
    current = get_settings().model_dump(mode="json")
    for k, v in updates.items():
        if v is not None and k in current:
            current[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    # 不把完整 key 打日志；文件仅本地保存
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_settings(path)


PREVIEW_WHITELIST = {".obj", ".fbx", ".blend", ".gltf", ".glb"}
VIEW_NAMES_4 = ["front", "right", "back", "left"]
VIEW_NAMES_6 = ["front", "right", "back", "left", "top", "bottom"]


def view_names_for_count(n: int) -> list[str]:
    if n <= 4:
        return VIEW_NAMES_4[: max(1, n)]
    if n <= 6:
        return VIEW_NAMES_6[:n]
    # 7–8：在 6 基础上重复对角近似（原型简化）
    extra = [f"extra_{i}" for i in range(n - 6)]
    return VIEW_NAMES_6 + extra
