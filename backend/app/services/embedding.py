"""SigLIP2 本地 Embedding：图像与文本共用同一向量空间。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)

_model = None
_processor = None
_device = None
_load_error: Optional[str] = None


def embedding_status() -> dict:
    return {
        "loaded": _model is not None,
        "device": str(_device) if _device else None,
        "error": _load_error,
    }


def load_siglip(model_path: Path) -> bool:
    global _model, _processor, _device, _load_error
    if _model is not None:
        return True
    try:
        from transformers import AutoModel, AutoProcessor

        if not model_path.exists():
            _load_error = f"权重目录不存在: {model_path}"
            logger.warning(_load_error)
            return False
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("Loading SigLIP2 from %s on %s", model_path, _device)
        _processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
        _model = AutoModel.from_pretrained(str(model_path), local_files_only=True)
        _model.to(_device)
        _model.eval()
        _load_error = None
        return True
    except Exception as e:
        _load_error = str(e)
        logger.exception("SigLIP2 load failed")
        _model = None
        _processor = None
        return False


def _to_vec(feats) -> np.ndarray:
    """把模型输出统一成 1D float32 向量。"""
    if not torch.is_tensor(feats):
        if hasattr(feats, "pooler_output") and feats.pooler_output is not None:
            feats = feats.pooler_output
        elif hasattr(feats, "image_embeds") and feats.image_embeds is not None:
            feats = feats.image_embeds
        elif hasattr(feats, "text_embeds") and feats.text_embeds is not None:
            feats = feats.text_embeds
        elif hasattr(feats, "last_hidden_state"):
            feats = feats.last_hidden_state[:, 0, :]
        else:
            raise TypeError(f"无法从输出提取向量: {type(feats)}")
    arr = feats.detach().float().cpu().numpy()
    return np.asarray(arr, dtype=np.float32).reshape(-1)


@torch.inference_mode()
def embed_image(image_path: Path) -> np.ndarray:
    if _model is None or _processor is None:
        raise RuntimeError(_load_error or "SigLIP2 未加载")
    image = Image.open(image_path).convert("RGB")
    inputs = _processor(images=image, return_tensors="pt")
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    if hasattr(_model, "get_image_features"):
        feats = _model.get_image_features(**inputs)
    else:
        out = _model(**inputs)
        feats = out
    return _to_vec(feats)


@torch.inference_mode()
def embed_text(text: str) -> np.ndarray:
    if _model is None or _processor is None:
        raise RuntimeError(_load_error or "SigLIP2 未加载")
    inputs = _processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    if hasattr(_model, "get_text_features"):
        feats = _model.get_text_features(**inputs)
    else:
        feats = _model(**inputs)
    return _to_vec(feats)


@torch.inference_mode()
def embed_pil(image: Image.Image) -> np.ndarray:
    if _model is None or _processor is None:
        raise RuntimeError(_load_error or "SigLIP2 未加载")
    image = image.convert("RGB")
    inputs = _processor(images=image, return_tensors="pt")
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    if hasattr(_model, "get_image_features"):
        feats = _model.get_image_features(**inputs)
    else:
        feats = _model(**inputs)
    return _to_vec(feats)
