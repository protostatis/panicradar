"""Embedding backend abstraction.

Decouples ``SemanticSentimentAnalyzer`` from the concrete embedding source so
the same anchor-similarity scoring works against any provider (local
SentenceTransformer, OpenRouter API, HuggingFace inference, …).

All providers implement one method::

    encode(texts: list[str], normalize: bool = True) -> np.ndarray

returning a ``(n_texts, dim)`` float32 array. Embeddings are L2-normalised by
default so downstream cosine similarity is a plain dot product.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from ..logging_config import logger


class EmbeddingProvider(ABC):
    """Abstract embedding backend."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Output embedding dimensionality."""

    @abstractmethod
    def encode(self, texts: list[str] | str, normalize: bool = True) -> np.ndarray:
        """Embed one or more texts into a ``(n, dim)`` float32 array."""

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        """Convenience wrapper returning a single ``(dim,)`` vector."""
        out = self.encode([text], normalize=normalize)
        return out[0]


class LocalSentenceTransformerProvider(EmbeddingProvider):
    """Wraps a locally-cached ``sentence-transformers`` model.

    Backwards-compatible with the original ``SemanticSentimentAnalyzer``
    behaviour: ``model_name="all-MiniLM-L6-v2"`` produces identical vectors to
    the previous hardcoded path.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str | None = None,
        **model_kwargs: Any,
    ) -> None:
        # Imported lazily so importing this module does not require torch.
        from sentence_transformers import SentenceTransformer

        logger.info("Loading local sentence-transformer: %s", model_name)
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device, **model_kwargs)
        self._dim = int(self.model.get_sentence_embedding_dimension())
        logger.info("Embedding dim=%d", self._dim)

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, texts: list[str] | str, normalize: bool = True) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        emb = self.model.encode(
            texts,
            normalize_embeddings=normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(emb, dtype=np.float32)


class OpenRouterEmbeddingProvider(EmbeddingProvider):
    """Calls the OpenRouter ``/embeddings`` endpoint (OpenAI-compatible).

    Designed for hosted models such as ``qwen/qwen3-embedding-8b`` that are too
    large to run locally. Batches requests, retries transient failures, and
    caches vectors on disk to keep repeat runs cheap.
    """

    BASE_URL = "https://openrouter.ai/api/v1/embeddings"

    def __init__(
        self,
        model: str = "qwen/qwen3-embedding-8b",
        api_key: str | None = None,
        dimensions: int | None = None,
        batch_size: int = 64,
        max_retries: int = 4,
        cache_path: str | None = "data/openrouter_embeddings_cache.npz",
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is required for OpenRouterEmbeddingProvider"
            )
        self.dimensions = dimensions  # MRL-trimmed dims; None = model default
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.cache_path = cache_path
        self._cache: dict[str, np.ndarray] = {}
        self._cache_dirty = False
        self._load_cache()
        # Dim is only known after the first successful call (depends on model +
        # requested ``dimensions``). Until then we expose a sentinel.
        self._dim: int | None = None

    # -- cache -----------------------------------------------------------
    def _load_cache(self) -> None:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            data = np.load(self.cache_path, allow_pickle=False)
            texts = data["texts"].astype(str)
            vecs = data["vectors"]
            for t, v in zip(texts, vecs):
                self._cache[t] = v
            logger.info("Loaded %d cached OpenRouter embeddings", len(self._cache))
        except Exception as exc:  # noqa: BLE001 - corrupt cache is non-fatal
            logger.warning("Failed to load embedding cache: %s", exc)

    def _save_cache(self) -> None:
        if not self.cache_path or not self._cache_dirty or not self._cache:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            texts = np.array(list(self._cache.keys()))
            vecs = np.stack(list(self._cache.values()))
            np.savez(self.cache_path, texts=texts, vectors=vecs)
            self._cache_dirty = False
            logger.info("Saved %d embeddings to cache", len(self._cache))
        except Exception as exc:  # noqa: BLE001 - cache failure is non-fatal
            logger.warning("Failed to save embedding cache: %s", exc)

    # -- HTTP ------------------------------------------------------------
    def _post_batch(self, batch: list[str]) -> np.ndarray:
        import requests  # local import keeps module import cheap

        payload: dict[str, Any] = {"model": self.model, "input": batch}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/protostatis/panicradar",
            "X-Title": "crypto-sentiment-crawler",
        }
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    self.BASE_URL, headers=headers, json=payload, timeout=120
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise RuntimeError(f"transient {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
                vecs = [np.asarray(item["embedding"], dtype=np.float32) for item in data["data"]]
                if self._dim is None and vecs:
                    self._dim = vecs[0].shape[0]
                return np.stack(vecs)
            except Exception as exc:  # noqa: BLE001 - retry broad transient faults
                last_exc = exc
                backoff = 2 ** attempt
                logger.warning(
                    "OpenRouter embeddings attempt %d/%d failed: %s (retry in %ds)",
                    attempt + 1,
                    self.max_retries,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
        raise RuntimeError(
            f"OpenRouter embeddings failed after {self.max_retries} retries: {last_exc}"
        )

    # -- public API ------------------------------------------------------
    @property
    def dim(self) -> int:
        if self._dim is None:
            # Determine dim from a cached vector, or by fetching a warmup.
            if self._cache:
                self._dim = next(iter(self._cache.values())).shape[0]
            else:
                self.encode(["warmup"], normalize=False)
        if self._dim is None:
            raise RuntimeError(
                "Failed to determine embedding dimension"
            )
        return self._dim

    def encode(self, texts: list[str] | str, normalize: bool = True) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        # Separate cached from uncached.
        to_fetch: list[tuple[int, str]] = []
        cached: dict[int, np.ndarray] = {}
        for i, t in enumerate(texts):
            if t in self._cache:
                cached[i] = self._cache[t]
            else:
                to_fetch.append((i, t))
        # Determine dimension lazily on the first uncached item.
        if to_fetch and self._dim is None:
            first_idx, first_text = to_fetch[0]
            first_vec = self._post_batch([first_text])[0]
            self._dim = first_vec.shape[0]
            self._cache[first_text] = first_vec
            self._cache_dirty = True
            cached[first_idx] = first_vec
            to_fetch = to_fetch[1:]
        # Now we know the dim — allocate and fill.
        dim = self._dim or (next(iter(cached.values())).shape[0] if cached else 4096)
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, vec in cached.items():
            out[i] = vec
        # Fetch remaining batches.
        for start in range(0, len(to_fetch), self.batch_size):
            chunk = to_fetch[start : start + self.batch_size]
            batch_texts = [t for _, t in chunk]
            vecs = self._post_batch(batch_texts)
            for j, (idx, t) in enumerate(chunk):
                self._cache[t] = vecs[j]
                out[idx] = vecs[j]
            self._cache_dirty = True
        self._save_cache()
        if normalize:
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            out = out / norms
        return out


def get_provider(
    backend: str = "local",
    *,
    model: str | None = None,
    **kwargs: Any,
) -> EmbeddingProvider:
    """Factory keyed off ``backend`` (``"local"`` | ``"openrouter"``).

    Reads defaults from environment to ease CLI usage::

        EMBEDDING_BACKEND=openrouter EMBEDDING_MODEL=qwen/qwen3-embedding-8b
    """
    backend = (backend or os.environ.get("EMBEDDING_BACKEND", "local")).lower()
    if backend in ("local", "minilm", "sentence-transformers", "st"):
        return LocalSentenceTransformerProvider(
            model_name=model or os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            **kwargs,
        )
    if backend in ("openrouter", "or", "api"):
        return OpenRouterEmbeddingProvider(
            model=model or os.environ.get("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"),
            **kwargs,
        )
    raise ValueError(f"Unknown embedding backend: {backend!r}")
