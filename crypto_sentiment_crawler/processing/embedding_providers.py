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
    large to run locally.  Batches requests, retries transient failures with
    exponential backoff and jitter, keeps a model-scoped disk cache with atomic
    writes, and uses a simple circuit-breaker to avoid hammering the API during
    prolonged outages.
    """

    BASE_URL = "https://openrouter.ai/api/v1/embeddings"

    # Circuit‑breaker state.
    _CIRCUIT_OPEN_AFTER = 4       # consecutive failures
    _CIRCUIT_COOLDOWN_S = 120.0   # wait before retrying a single probe

    def __init__(
        self,
        model: str = "qwen/qwen3-embedding-8b",
        api_key: str | None = None,
        dimensions: int | None = None,
        batch_size: int = 64,
        max_retries: int = 2,
        request_timeout_s: float = 30.0,
        cache_path: str | None = "data/openrouter_embeddings_cache.npz",
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is required for OpenRouterEmbeddingProvider"
            )
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.request_timeout_s = request_timeout_s
        self.cache_path = cache_path
        self._cache: dict[str, np.ndarray] = {}
        self._cache_dirty = False
        # --- circuit breaker ---
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0
        # --- load cache (with metadata validation) ---
        self._cache_namespace = self._make_cache_namespace()
        self._load_cache()
        # Dim is only known after the first successful API call.
        self._dim: int | None = None

    # -- cache identity ------------------------------------------------------
    def _make_cache_namespace(self) -> str:
        """Return a unique key namespace for this provider configuration."""
        parts = [self.model]
        if self.dimensions is not None:
            parts.append(f"d{self.dimensions}")
        return "::".join(parts)

    @staticmethod
    def _text_key(text: str) -> str:
        """Stable key for a text snippet (prefix prevents pure-numeric collisions)."""
        return "t::" + text

    # -- cache persistence ---------------------------------------------------
    def _load_cache(self) -> None:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            data = np.load(self.cache_path, allow_pickle=False)
            # Validate namespace metadata to prevent model-version collisions.
            ns = str(data.get("_namespace", ""))
            if ns != self._cache_namespace:
                logger.info(
                    "Cache namespace mismatch (%s → %s); discarding old cache",
                    ns, self._cache_namespace,
                )
                return
            texts = data["texts"].astype(str)
            vecs = data["vectors"]
            if len(texts) != len(vecs):
                logger.warning("Cache text/vector length mismatch; discarding")
                return
            for t, v in zip(texts, vecs):
                self._cache[t] = np.asarray(v, dtype=np.float32)
            logger.info("Loaded %d cached embeddings (ns=%s)", len(self._cache), ns)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load embedding cache: %s", exc)

    def _save_cache(self) -> None:
        if not self.cache_path or not self._cache_dirty or not self._cache:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            texts = np.array(list(self._cache.keys()))
            vecs = np.stack(list(self._cache.values()))
            # Atomic write: tempfile → rename.
            tmp = self.cache_path + ".tmp"
            np.savez(
                tmp,
                _namespace=np.array(self._cache_namespace),
                texts=texts,
                vectors=vecs,
            )
            os.replace(tmp, self.cache_path)
            self._cache_dirty = False
            logger.info("Saved %d embeddings to cache", len(self._cache))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save embedding cache: %s", exc)

    # -- circuit breaker -----------------------------------------------------
    def _check_circuit(self) -> None:
        if self._consecutive_failures < self._CIRCUIT_OPEN_AFTER:
            return
        if time.monotonic() < self._circuit_open_until:
            raise RuntimeError(
                f"OpenRouter circuit open: {self._consecutive_failures} consecutive "
                f"failures; cooling off for {self._CIRCUIT_COOLDOWN_S:.0f}s"
            )
        # Cooldown expired — allow one probe.
        logger.info("Circuit cooldown elapsed; sending probe request")
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._CIRCUIT_OPEN_AFTER:
            self._circuit_open_until = (
                time.monotonic() + self._CIRCUIT_COOLDOWN_S
            )
            logger.warning(
                "Circuit opened after %d consecutive failures; "
                "pausing for %.0fs",
                self._consecutive_failures,
                self._CIRCUIT_COOLDOWN_S,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    # -- HTTP ----------------------------------------------------------------
    def _post_batch(self, batch: list[str]) -> np.ndarray:
        import requests  # local import

        self._check_circuit()

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
        # Distinguish permanent client errors (never retry) from transient ones.
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=self.request_timeout_s,
                )
                if resp.status_code in (400, 401, 402, 403, 404):
                    # Permanent — do NOT retry.
                    self._record_failure()
                    raise RuntimeError(
                        f"Permanent OpenRouter error {resp.status_code}: "
                        f"{resp.text[:300]}"
                    ) from None
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise RuntimeError(
                        f"Transient {resp.status_code}: {resp.text[:200]}"
                    )
                resp.raise_for_status()
                data = resp.json()

                # --- response validation ---
                items = data.get("data", [])
                if len(items) != len(batch):
                    raise RuntimeError(
                        f"Got {len(items)} embeddings, expected {len(batch)}"
                    )
                vecs: list[np.ndarray] = []
                for idx, item in enumerate(items):
                    raw = item.get("embedding", [])
                    arr = np.asarray(raw, dtype=np.float32)
                    if arr.ndim != 1 or arr.shape[0] == 0:
                        raise RuntimeError(f"Bad embedding shape at idx {idx}")
                    if not np.all(np.isfinite(arr)):
                        raise RuntimeError(f"NaN/Inf in embedding at idx {idx}")
                    if self._dim is None and idx == 0:
                        self._dim = int(arr.shape[0])
                    elif self._dim is not None and arr.shape[0] != self._dim:
                        raise RuntimeError(
                            f"Dimension mismatch at idx {idx}: "
                            f"{arr.shape[0]} != {self._dim}"
                        )
                    vecs.append(arr)
                # --- success ---
                self._record_success()
                return np.stack(vecs)

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._record_failure()  # may open circuit
                if attempt < self.max_retries:
                    # Only retry *transient* failures.
                    if isinstance(exc, RuntimeError) and "Transient" not in str(exc):
                        break
                    backoff = (2 ** attempt) + (0.1 * time.monotonic() % 1)
                    logger.warning(
                        "OpenRouter attempt %d/%d failed: %s (retry in %.1fs)",
                        attempt + 1, self.max_retries, exc, backoff,
                    )
                    time.sleep(backoff)
                    self._check_circuit()

        raise RuntimeError(
            f"OpenRouter embeddings failed ({self.max_retries+1} attempts): {last_exc}"
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
    api_key: str | None = None,
    **kwargs: Any,
) -> EmbeddingProvider:
    """Factory keyed off ``backend`` (``"local"`` | ``"openrouter"``).

    With no argument, uses the default local MiniLM.  Set environment
    variables or pass explicit kwargs to override.
    """
    backend = (backend or "local").lower()
    if backend in ("local", "minilm", "sentence-transformers", "st"):
        return LocalSentenceTransformerProvider(
            model_name=model or "all-MiniLM-L6-v2",
            **kwargs,
        )
    if backend in ("openrouter", "or", "api"):
        return OpenRouterEmbeddingProvider(
            model=model or "qwen/qwen3-embedding-8b",
            api_key=api_key,
            **kwargs,
        )
    raise ValueError(f"Unknown embedding backend: {backend!r}")
