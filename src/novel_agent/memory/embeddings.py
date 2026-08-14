"""嵌入提供方:测试默认 hash/mock,真实供应商走 env(与模型槽位同精神)。"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, assert_never

import httpx

from novel_agent.config import EmbeddingConfig


class EmbeddingProvider(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把文本编成等长向量。测试实现必须确定性、无网络。"""


def tokenize(text: str) -> list[str]:
    """中英混合的确定性字/词 n-gram,供 hash 嵌入与词面重叠打分。"""
    compact = "".join(text.split()).casefold()
    if not compact:
        return []
    tokens = [compact]
    for i, char in enumerate(compact):
        tokens.append(char)
        if i + 1 < len(compact):
            tokens.append(compact[i : i + 2])
        if i + 2 < len(compact):
            tokens.append(compact[i : i + 3])
    return tokens


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def lexical_overlap(query: str, text: str) -> float:
    left = set(tokenize(query))
    right = set(tokenize(text))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class HashEmbedding:
    """无网络的确定性哈希嵌入。默认用于 pytest 与本地 mock。"""

    def __init__(self, dim: int = 64) -> None:
        if dim < 8:
            raise ValueError("hash embedding dim 必须 >= 8")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dim
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign
        return l2_normalize(vector)


class OpenAICompatEmbedding:
    """OpenAI 兼容 /embeddings。仅当 env 显式配置真实槽位时使用。"""

    def __init__(self, config: EmbeddingConfig) -> None:
        if config.api_key is None or not config.base_url:
            raise ValueError("openai_compat 嵌入需要 api_key 与 base_url")
        self._config = config
        self.dim = config.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        assert self._config.api_key is not None and self._config.base_url
        response = httpx.post(
            f"{self._config.base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {self._config.api_key.get_secret_value()}"
            },
            json={"model": self._config.model, "input": texts},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError("嵌入接口返回条数与输入不一致")
        vectors: list[list[float]] = []
        for row in sorted(rows, key=lambda item: int(item.get("index", 0))):
            raw = row.get("embedding")
            if not isinstance(raw, list) or not raw:
                raise ValueError("嵌入接口缺少 embedding")
            vectors.append([float(item) for item in raw])
        self.dim = len(vectors[0])
        return vectors


def build_embedder(config: EmbeddingConfig) -> EmbeddingProvider:
    provider = config.provider
    if provider == "mock":
        return HashEmbedding(dim=config.dim)
    if provider == "openai_compat":
        return OpenAICompatEmbedding(config)
    assert_never(provider)
