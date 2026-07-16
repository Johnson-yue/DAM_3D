"""
faiss 向量索引封装（教学级注释版）

本文件面向「从未用过 faiss」的读者。读完应能理解：
1. faiss 是什么、为什么适合相似检索
2. IndexFlatIP 如何做「归一化向量 → 内积 ≈ 余弦相似度」
3. 如何 add / search，以及 faiss 内部 ID 如何与 SQLite 中的 asset/view 对齐
4. 为何本项目采用「每视图一条向量」，检索后再按资产 Max 聚合

------------------------------------------------
一、faiss 是什么？
------------------------------------------------
faiss（Facebook AI Similarity Search）是一个高效的相似度检索库。
给定一个查询向量 q，它能在海量已入库向量中快速找出「最像」的 Top-N。

本原型库规模很小（测试集仅几个资产 × 几张多视图），因此使用最简单、
最精确的暴力检索索引：IndexFlatIP（Flat = 暴力扫全库；IP = Inner Product 内积）。

------------------------------------------------
二、为什么用内积（IP）而不是 L2？
------------------------------------------------
SigLIP / CLIP 类模型输出的 embedding，通常会做 L2 归一化：
    v = v / ||v||
对两个已归一化向量，有：
    cos(a, b) = a · b
因此「内积越大 = 越相似」。IndexFlatIP 正好最大化内积。

若忘了归一化就直接 add，相似度会失真——所以本文件在 add/search 前都会 normalize。

------------------------------------------------
三、ID 映射策略（非常重要）
------------------------------------------------
faiss 自己只存「第 i 行向量」，默认 ID 就是 0,1,2,...（连续下标）。
我们还需要知道：第 i 行对应哪个 asset 的哪个视角。

做法：
- 使用 faiss.IndexIDMap2 包一层，允许我们指定外部 int64 ID（= SQLite view_embeddings.faiss_id）
- SQLite 表 view_embeddings 保存：asset_id, view_id, image_path, faiss_id, dim
- 检索返回 faiss_id 列表后，再用 SQLite 反查资产与视角

------------------------------------------------
四、持久化
------------------------------------------------
index 存到 library/faiss/views.index
下次启动 load；若文件不存在则新建空索引（维度在首次 add 时确定）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

from ..config import get_settings


class FaissViewIndex:
    """视图级向量索引：一行 = 一张多视图图的 embedding。"""

    def __init__(self, dim: Optional[int] = None):
        self.settings = get_settings()
        self.index_path = self.settings.faiss_dir / "views.index"
        self.meta_path = self.settings.faiss_dir / "views_meta.json"
        self.dim: Optional[int] = dim
        self.index: Optional[faiss.IndexIDMap2] = None
        self._load_or_init()

    def _new_index(self, dim: int) -> faiss.IndexIDMap2:
        """
        创建空索引：
        1) IndexFlatIP(dim)：暴力内积检索，精确、适合小库
        2) IndexIDMap2：允许 add_with_ids，用自定义 faiss_id
        """
        flat = faiss.IndexFlatIP(dim)
        return faiss.IndexIDMap2(flat)

    def _load_or_init(self) -> None:
        self.settings.faiss_dir.mkdir(parents=True, exist_ok=True)
        if self.index_path.exists():
            # faiss.read_index 读回磁盘上的索引对象
            raw = faiss.read_index(str(self.index_path))
            # 若已是 IDMap2 直接用；否则包一层（兼容极端情况）
            if isinstance(raw, faiss.IndexIDMap2):
                self.index = raw
            else:
                self.index = faiss.IndexIDMap2(raw)
            self.dim = self.index.d
            return
        # 尚无文件：若调用方已知 dim 则立刻建；否则等第一次 add
        if self.dim is not None:
            self.index = self._new_index(self.dim)
            self._save()

    def _ensure(self, dim: int) -> None:
        if self.index is None:
            self.dim = dim
            self.index = self._new_index(dim)
            return
        if self.dim != dim:
            raise ValueError(f"向量维度不一致: index.dim={self.dim}, got={dim}")

    @staticmethod
    def normalize(vectors: np.ndarray) -> np.ndarray:
        """
        L2 归一化到单位球。
        输入形状 (n, dim) 或 (dim,)；输出 float32 且保证为二维 (n, dim)。
        """
        x = np.asarray(vectors, dtype=np.float32)
        # SigLIP 有时会给出多余维度，统一压成 (n, dim)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        elif x.ndim > 2:
            x = x.reshape(x.shape[0], -1)
        x = np.ascontiguousarray(x)
        faiss.normalize_L2(x)
        return x

    def add(self, vector: np.ndarray, faiss_id: int) -> None:
        """
        写入一条视图向量。

        参数:
          vector: shape (dim,) 或 (1, dim)
          faiss_id: 外部 ID，必须与 SQLite view_embeddings.faiss_id 一致且全局唯一
        """
        x = self.normalize(vector)
        dim = x.shape[1]
        self._ensure(dim)
        ids = np.array([faiss_id], dtype=np.int64)
        # add_with_ids：把向量与自定义 ID 绑在一起
        assert self.index is not None
        self.index.add_with_ids(x, ids)
        self._save()

    def add_batch(self, vectors: np.ndarray, faiss_ids: list[int]) -> None:
        """批量写入，形状 (n, dim)。"""
        x = self.normalize(vectors)
        self._ensure(x.shape[1])
        ids = np.asarray(faiss_ids, dtype=np.int64)
        assert self.index is not None
        self.index.add_with_ids(x, ids)
        self._save()

    def search(self, query: np.ndarray, top_n: int) -> list[tuple[int, float]]:
        """
        检索最相似的 top_n 条【视图级】结果。

        返回: [(faiss_id, score), ...]，score 为内积（归一化后≈余弦）
        """
        if self.index is None or self.index.ntotal == 0:
            return []
        q = self.normalize(query)
        n = min(top_n, self.index.ntotal)
        # search 返回 (scores, ids)，形状均为 (1, n)
        scores, ids = self.index.search(q, n)
        out: list[tuple[int, float]] = []
        for score, fid in zip(scores[0], ids[0]):
            if fid < 0:
                # faiss 用 -1 表示无效填充位
                continue
            out.append((int(fid), float(score)))
        return out

    def remove_ids(self, faiss_ids: list[int]) -> None:
        """按外部 ID 删除向量（资产重嵌入时会用到）。"""
        if self.index is None or not faiss_ids:
            return
        sel = faiss.IDSelectorBatch(np.asarray(faiss_ids, dtype=np.int64))
        self.index.remove_ids(sel)
        self._save()

    def _save(self) -> None:
        assert self.index is not None
        faiss.write_index(self.index, str(self.index_path))
        meta = {"dim": self.dim, "ntotal": int(self.index.ntotal)}
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @property
    def ntotal(self) -> int:
        return 0 if self.index is None else int(self.index.ntotal)


# 进程内单例，避免重复读盘
_index_singleton: Optional[FaissViewIndex] = None


def get_faiss_index() -> FaissViewIndex:
    global _index_singleton
    if _index_singleton is None:
        _index_singleton = FaissViewIndex()
    return _index_singleton


def reset_faiss_index() -> FaissViewIndex:
    """测试或库根变更后重建单例。"""
    global _index_singleton
    _index_singleton = FaissViewIndex()
    return _index_singleton
