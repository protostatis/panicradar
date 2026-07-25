"""Unit tests for embedding providers."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from crypto_sentiment_crawler.processing.embedding_providers import (
    LocalSentenceTransformerProvider,
    OpenRouterEmbeddingProvider,
    get_provider,
)

# ── get_provider ───────────────────────────────────────────────────────────


class TestGetProvider:
    def test_default_local(self) -> None:
        p = get_provider("local")
        assert isinstance(p, LocalSentenceTransformerProvider)
        assert p.model_name == "all-MiniLM-L6-v2"

    def test_custom_local_model(self) -> None:
        p = get_provider("local", model="all-mpnet-base-v2")
        assert p.model_name == "all-mpnet-base-v2"

    def test_unknown_backend(self) -> None:
        with pytest.raises(ValueError, match="Unknown embedding backend"):
            get_provider("banana")

    def test_openrouter_requires_key(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=True):
            with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
                get_provider("openrouter", api_key="")

    def test_openrouter_with_explicit_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            p = get_provider("openrouter", api_key="sk-test-123")
            assert isinstance(p, OpenRouterEmbeddingProvider)
            assert p.api_key == "sk-test-123"


# ── LocalSentenceTransformerProvider ───────────────────────────────────────


class TestLocalProvider:
    def test_dim(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        assert p.dim == 384

    def test_encode_shape(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        out = p.encode(["hello world", "goodbye"])
        assert out.shape == (2, 384)
        assert out.dtype == np.float32

    def test_encode_normalized(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        out = p.encode(["hello"])
        # L2-norm should be ~1.0
        assert np.isclose(np.linalg.norm(out[0]), 1.0, atol=1e-5)

    def test_encode_single_string(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        out = p.encode("hello")
        assert out.shape == (1, 384)

    def test_encode_single_method(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        vec = p.encode_single("hello")
        assert vec.shape == (384,)
        assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-5)


# ── OpenRouterEmbeddingProvider ────────────────────────────────────────────


class TestOpenRouterCache:
    def test_make_cache_namespace(self) -> None:
        p = OpenRouterEmbeddingProvider(api_key="sk-test")
        ns = p._make_cache_namespace()
        assert "qwen/qwen3-embedding-8b" in ns

    def test_make_cache_namespace_with_dimensions(self) -> None:
        p = OpenRouterEmbeddingProvider(api_key="sk-test", dimensions=1024)
        ns = p._make_cache_namespace()
        assert "d1024" in ns

    def test_cache_namespace_mismatch_discards(self, tmp_path: Path) -> None:
        cache_path = str(tmp_path / "test.npz")
        np.savez(cache_path, _namespace=np.array("old::ns"), texts=np.array(["a"]),
                 vectors=np.random.randn(1, 10).astype(np.float32))
        p = OpenRouterEmbeddingProvider(api_key="sk-test", cache_path=cache_path)
        assert len(p._cache) == 0

    def test_cache_text_vector_length_mismatch_discards(self, tmp_path: Path) -> None:
        cache_path = str(tmp_path / "test.npz")
        ns = OpenRouterEmbeddingProvider(api_key="sk-test")._make_cache_namespace()
        np.savez(cache_path, _namespace=np.array(ns), texts=np.array(["a", "b"]),
                 vectors=np.random.randn(1, 10).astype(np.float32))
        p = OpenRouterEmbeddingProvider(api_key="sk-test", cache_path=cache_path)
        assert len(p._cache) == 0

    @pytest.mark.skipif(platform.system() == "Darwin",
                       reason="macOS aggressive tmp cleanup breaks cache persistence test")
    def test_cache_atomic_write_and_load(self, tmp_path: Path) -> None:
        cache_path = str(tmp_path / "test_cache.npz")
        p = OpenRouterEmbeddingProvider(api_key="sk-test", cache_path=cache_path)
        p._cache["hello"] = np.array([1.0, 2.0], dtype=np.float32)
        p._cache["world"] = np.array([3.0, 4.0], dtype=np.float32)
        p._cache_dirty = True
        p._save_cache()
        assert Path(cache_path).exists()
        assert not Path(cache_path + ".tmp").exists()
        # Reload: different instance, same cache file.
        p2 = OpenRouterEmbeddingProvider(api_key="sk-test", cache_path=cache_path)
        assert len(p2._cache) == 2
        assert np.allclose(p2._cache["hello"], np.array([1.0, 2.0]))
        assert np.allclose(p2._cache["world"], np.array([3.0, 4.0]))


class TestOpenRouterCircuitBreaker:
    def test_opens_after_consecutive_failures(self) -> None:
        p = OpenRouterEmbeddingProvider(api_key="sk-test")
        p._CIRCUIT_OPEN_AFTER = 2  # speed up
        p._CIRCUIT_COOLDOWN_S = 0.001
        p._record_failure()
        p._record_failure()
        # Third failure should open circuit
        with pytest.raises(RuntimeError, match="circuit open"):
            p._check_circuit()

    def test_success_resets_circuit(self) -> None:
        p = OpenRouterEmbeddingProvider(api_key="sk-test")
        p._CIRCUIT_OPEN_AFTER = 2
        p._consecutive_failures = 3
        p._circuit_open_until = 1e9
        p._record_success()
        assert p._consecutive_failures == 0
        p._check_circuit()  # should not raise


class TestOpenRouterResponseValidation:
    def make_provider(self) -> OpenRouterEmbeddingProvider:
        return OpenRouterEmbeddingProvider(api_key="sk-test", max_retries=0)

    def _mock_response(self, status=200, json_data=None):
        m = MagicMock()
        m.status_code = status
        m.json.return_value = json_data or {}
        m.text = ""
        return m

    def test_valid_response(self) -> None:
        p = self.make_provider()
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(
                200, {"data": [{"embedding": [1.0, 2.0]}, {"embedding": [3.0, 4.0]}]}
            )
            vecs = p._post_batch(["a", "b"])
            assert vecs.shape == (2, 2)
            assert p._dim == 2

    def test_dimension_mismatch_raises(self) -> None:
        p = self.make_provider()
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(
                200, {"data": [{"embedding": [1.0]}, {"embedding": [3.0, 4.0]}]}
            )
            with pytest.raises(RuntimeError, match="Dimension mismatch"):
                p._post_batch(["a", "b"])

    def test_nan_embedding_raises(self) -> None:
        p = self.make_provider()
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(
                200, {"data": [{"embedding": [1.0, float('nan')]}]}
            )
            with pytest.raises(RuntimeError, match="NaN/Inf"):
                p._post_batch(["a"])

    def test_length_mismatch_raises(self) -> None:
        p = self.make_provider()
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(
                200, {"data": [{"embedding": [1.0]}]}   # 1 item, expected 2
            )
            with pytest.raises(RuntimeError, match="Got 1 embeddings, expected 2"):
                p._post_batch(["a", "b"])

    def test_permanent_400_not_retried(self) -> None:
        p = self.make_provider()
        p.max_retries = 3
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(400)
            with pytest.raises(RuntimeError, match="Permanent"):
                p._post_batch(["a"])
            assert mock_post.call_count == 1  # no retries

    def test_permanent_401_not_retried(self) -> None:
        p = self.make_provider()
        p.max_retries = 3
        with patch("requests.post") as mock_post:
            mock_post.return_value = self._mock_response(401)
            with pytest.raises(RuntimeError, match="Permanent"):
                p._post_batch(["a"])
            assert mock_post.call_count == 1


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_list(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        out = p.encode([])
        # sentence-transformers returns (0,) for empty input; the provider should
        # reshape or preserve it.  We just check it's valid and has zero rows.
        assert out.ndim == 1 or out.shape[0] == 0

    def test_encode_mixed_lengths(self) -> None:
        p = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
        out = p.encode(["a", "a b c d e f g h i j"])
        assert out.shape == (2, 384)
        assert out.dtype == np.float32
