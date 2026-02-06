"""Tests for GP-Beta hybrid model."""

import numpy as np
import pytest

from crypto_sentiment_crawler.bayesian.gp_model import GPSourceModel, SourceFeatures


def _make_features(n: int, d: int = 7, source_type: str = "social") -> list[SourceFeatures]:
    """Create n random SourceFeatures with d-dimensional vectors."""
    rng = np.random.RandomState(42)
    return [
        SourceFeatures(
            source=f"source_{i}",
            features=rng.randn(d),
            source_type=source_type,
        )
        for i in range(n)
    ]


def _make_clustered_features() -> list[SourceFeatures]:
    """Create features with two clear clusters (Bitcoin-like and altcoin-like)."""
    rng = np.random.RandomState(42)
    features = []
    # Cluster 1: Bitcoin subs (similar features)
    for i in range(5):
        features.append(SourceFeatures(
            source=f"reddit_bitcoin_{i}",
            features=rng.randn(7) * 0.1 + np.array([1, 0.5, 0.3, 0.2, 0.1, 0.7, 3.0]),
            source_type="social",
        ))
    # Cluster 2: Altcoin subs (different features)
    for i in range(5):
        features.append(SourceFeatures(
            source=f"reddit_altcoin_{i}",
            features=rng.randn(7) * 0.1 + np.array([-1, 1.5, 0.8, 0.9, 0.5, 0.3, 1.5]),
            source_type="social",
        ))
    return features


class TestKernelMatrix:
    def test_positive_semi_definite(self):
        """Kernel matrix must be PSD."""
        model = GPSourceModel()
        features = _make_features(10)
        X = np.array([f.features for f in features])
        types = [f.source_type for f in features]

        K = model.compute_kernel_matrix(X, types)
        eigenvalues = np.linalg.eigvalsh(K)
        assert np.all(eigenvalues >= -1e-10), f"Negative eigenvalue: {eigenvalues.min()}"

    def test_symmetric(self):
        """Kernel matrix must be symmetric."""
        model = GPSourceModel()
        features = _make_features(8)
        X = np.array([f.features for f in features])
        types = [f.source_type for f in features]

        K = model.compute_kernel_matrix(X, types)
        np.testing.assert_allclose(K, K.T)

    def test_category_bonus(self):
        """Sources with same type should have higher kernel values."""
        model = GPSourceModel(category_variance=1.0)
        X = np.array([[0.0] * 7, [0.0] * 7, [0.0] * 7])
        types = ["social", "social", "forum"]

        K = model.compute_kernel_matrix(X, types)
        # social-social > social-forum (same features, different type bonus)
        assert K[0, 1] > K[0, 2]


class TestProbitRoundtrip:
    def test_roundtrip(self):
        """Phi(Phi^-1(x)) should be approximately x."""
        from scipy.special import ndtr, ndtri
        x = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        roundtripped = ndtr(ndtri(x))
        np.testing.assert_allclose(roundtripped, x, atol=1e-10)


class TestFit:
    def test_basic_fit(self):
        """Model should fit without errors."""
        model = GPSourceModel()
        features = _make_features(10)
        alphas = np.ones(10) * 5
        betas = np.ones(10) * 5
        model.fit(features, alphas, betas)
        assert model._fitted

    def test_predict_after_fit(self):
        """predict() should return correct shapes."""
        model = GPSourceModel()
        features = _make_features(10)
        alphas = np.ones(10) * 5
        betas = np.ones(10) * 5
        model.fit(features, alphas, betas)

        mu, sigma = model.predict()
        assert mu.shape == (10,)
        assert sigma.shape == (10, 10)

    def test_predict_before_fit_raises(self):
        """predict() should raise if not fitted."""
        model = GPSourceModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict()


class TestThompsonSampling:
    def test_samples_in_unit_interval(self):
        """All Thompson samples should be in [0, 1]."""
        model = GPSourceModel()
        features = _make_features(10)
        alphas = np.ones(10) * 5
        betas = np.ones(10) * 5
        model.fit(features, alphas, betas)

        samples = model.sample_thompson(n_samples=100)
        assert samples.shape == (100, 10)
        assert np.all(samples >= 0)
        assert np.all(samples <= 1)

    def test_sample_before_fit_raises(self):
        """sample_thompson() should raise if not fitted."""
        model = GPSourceModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.sample_thompson()


class TestCorrelatedUpdate:
    def test_similar_sources_correlated(self):
        """Updating one source should shift similar sources' posterior."""
        features = _make_clustered_features()

        # Fit with uniform beliefs
        model_uniform = GPSourceModel(length_scale=1.0, signal_variance=1.0)
        n = len(features)
        alphas_uniform = np.ones(n) * 5
        betas_uniform = np.ones(n) * 5
        model_uniform.fit(features, alphas_uniform, betas_uniform)
        mu_uniform, _ = model_uniform.predict()

        # Now make first Bitcoin source very accurate
        alphas_shifted = alphas_uniform.copy()
        alphas_shifted[0] = 50  # Very accurate source_0

        model_shifted = GPSourceModel(length_scale=1.0, signal_variance=1.0)
        model_shifted.fit(features, alphas_shifted, betas_uniform)
        mu_shifted, _ = model_shifted.predict()

        # Other Bitcoin sources (1-4) should shift more than altcoin sources (5-9)
        bitcoin_shift = np.mean(np.abs(mu_shifted[1:5] - mu_uniform[1:5]))
        altcoin_shift = np.mean(np.abs(mu_shifted[5:10] - mu_uniform[5:10]))

        assert bitcoin_shift > altcoin_shift, (
            f"Bitcoin shift ({bitcoin_shift:.4f}) should be > "
            f"altcoin shift ({altcoin_shift:.4f})"
        )

    def test_uniform_observations_give_near_uniform_posterior(self):
        """With uniform Beta(5,5) everywhere, posterior means should be near 0 (probit of 0.5)."""
        model = GPSourceModel()
        features = _make_features(10)
        alphas = np.ones(10) * 5
        betas = np.ones(10) * 5
        model.fit(features, alphas, betas)
        mu, _ = model.predict()

        # With uniform observations, probit(0.5) = 0
        np.testing.assert_allclose(mu, 0.0, atol=0.3)


class TestHyperparameterOptimization:
    def test_optimization_converges(self):
        """Optimization should converge on synthetic data."""
        rng = np.random.RandomState(42)
        features = _make_features(15)
        # Create non-uniform beliefs to give the optimizer something to work with
        alphas = rng.uniform(2, 20, size=15)
        betas = rng.uniform(2, 20, size=15)

        model = GPSourceModel()
        result = model.optimize_hyperparameters(features, alphas, betas)
        assert result["converged"]
        assert result["log_likelihood"] is not None

    def test_too_few_sources(self):
        """Should refuse to optimize with < 3 sources."""
        features = _make_features(2)
        alphas = np.ones(2) * 5
        betas = np.ones(2) * 5

        model = GPSourceModel()
        result = model.optimize_hyperparameters(features, alphas, betas)
        assert not result["converged"]
        assert result["reason"] == "too_few_sources"


class TestSerialization:
    def test_roundtrip(self):
        """to_dict -> from_dict should preserve hyperparameters."""
        model = GPSourceModel(
            length_scale=2.0,
            signal_variance=0.5,
            category_variance=0.8,
            noise_variance=0.2,
        )
        model.sources = ["a", "b"]

        data = model.to_dict()
        restored = GPSourceModel.from_dict(data)

        assert restored.length_scale == 2.0
        assert restored.signal_variance == 0.5
        assert restored.category_variance == 0.8
        assert restored.noise_variance == 0.2
        assert restored.sources == ["a", "b"]
        assert not restored._fitted  # Posterior must be recomputed

    def test_from_empty_dict(self):
        """from_dict with empty dict should use defaults."""
        model = GPSourceModel.from_dict({})
        assert model.length_scale == 1.0
        assert model.signal_variance == 1.0
