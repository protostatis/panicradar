"""Gaussian Process model for joint source informativeness.

Uses a GP prior over source feature vectors to model latent correlations
between sources. Beta distributions handle individual conjugate updates,
while the GP propagates belief updates across correlated sources.

Math:
    GP prior:    f(x_i) ~ GP(0, K(x_i, x_j))
    Probit link: p_i = Phi(f(x_i))
    Observations: Beta(alpha_i, beta_i) per source

    Moment matching (Beta -> Gaussian in probit space):
        mu_obs_i = Phi^-1(alpha_i / (alpha_i + beta_i))
        sigma^2_obs_i = 1 / (phi(mu_i)^2 * (alpha_i + beta_i + 1))

    GP posterior:
        Sigma_post = (K^-1 + Lambda)^-1  where Lambda = diag(1/sigma^2_obs)
        mu_post = Sigma_post * Lambda * mu_obs

    Thompson Sampling:
        z ~ N(mu_post, Sigma_post)
        theta_i = Phi(z_i)  -> correlated probabilities in [0, 1]
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize
from scipy.special import ndtr as norm_cdf  # Phi
from scipy.special import ndtri as norm_ppf  # Phi^-1
from scipy.stats import norm


@dataclass
class SourceFeatures:
    """Feature vector for a single source."""

    source: str
    features: np.ndarray  # 7D feature vector
    source_type: str = "social"  # social, forum, news, search


class GPSourceModel:
    """GP-Beta hybrid model for correlated source informativeness.

    Maintains a GP over source feature vectors with a composite kernel.
    Beta sufficient statistics are converted to Gaussian observations
    via probit moment matching, enabling joint posterior inference.
    """

    def __init__(
        self,
        length_scale: float = 1.0,
        signal_variance: float = 1.0,
        category_variance: float = 0.3,
        noise_variance: float = 0.1,
    ):
        self.length_scale = length_scale
        self.signal_variance = signal_variance
        self.category_variance = category_variance
        self.noise_variance = noise_variance

        # Posterior state (set after fit)
        self.mu_post: np.ndarray | None = None
        self.sigma_post: np.ndarray | None = None
        self.sources: list[str] | None = None
        self._fitted = False

    def compute_kernel_matrix(
        self, X: np.ndarray, types: list[str]
    ) -> np.ndarray:
        """Compute composite kernel matrix.

        k(x_i, x_j) = sigma_f^2 * exp(-||x_i - x_j||^2 / (2*l^2))
                     + sigma_cat^2 * delta(type_i, type_j)
                     + sigma_n^2 * I

        Args:
            X: Feature matrix (n x d)
            types: Source type for each row

        Returns:
            Kernel matrix (n x n)
        """
        n = X.shape[0]

        # RBF kernel
        dists_sq = np.sum((X[:, None, :] - X[None, :, :]) ** 2, axis=2)
        K_rbf = self.signal_variance * np.exp(
            -dists_sq / (2 * self.length_scale ** 2)
        )

        # Categorical kernel: same type -> bonus
        K_cat = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                if types[i] == types[j]:
                    K_cat[i, j] = self.category_variance

        # Noise kernel (diagonal)
        K_noise = self.noise_variance * np.eye(n)

        return K_rbf + K_cat + K_noise

    def fit(
        self,
        features: list[SourceFeatures],
        alphas: np.ndarray,
        betas: np.ndarray,
    ) -> None:
        """Fit GP posterior from Beta parameters and source features.

        Converts Beta(alpha, beta) observations to Gaussian in probit space
        via moment matching, then computes GP posterior.

        Args:
            features: List of SourceFeatures (one per source)
            alphas: Alpha parameters of Beta distributions
            betas: Beta parameters of Beta distributions
        """
        n = len(features)
        if n == 0:
            return

        self.sources = [f.source for f in features]

        # Build feature matrix
        X = np.array([f.features for f in features])
        types = [f.source_type for f in features]

        # Moment matching: Beta -> Gaussian in probit space
        mu_obs = np.zeros(n)
        sigma2_obs = np.zeros(n)

        for i in range(n):
            a, b = alphas[i], betas[i]
            p = a / (a + b)

            # Clamp to avoid infinities at probit boundaries
            p = np.clip(p, 0.01, 0.99)

            mu_obs[i] = norm_ppf(p)

            # Delta method variance: sigma^2 = 1 / (phi(mu)^2 * (a + b + 1))
            phi_val = norm.pdf(mu_obs[i])
            if phi_val > 1e-10:
                sigma2_obs[i] = 1.0 / (phi_val ** 2 * (a + b + 1))
            else:
                sigma2_obs[i] = 100.0  # Very uncertain

        # Compute kernel matrix
        K = self.compute_kernel_matrix(X, types)

        # GP posterior: Sigma_post = (K^-1 + Lambda)^-1
        # Lambda = diag(1 / sigma2_obs)
        Lambda = np.diag(1.0 / sigma2_obs)

        # Use Woodbury for numerical stability
        K_inv = np.linalg.inv(K + 1e-6 * np.eye(n))
        self.sigma_post = np.linalg.inv(K_inv + Lambda)
        self.mu_post = self.sigma_post @ Lambda @ mu_obs

        # Ensure symmetry
        self.sigma_post = (self.sigma_post + self.sigma_post.T) / 2

        self._fitted = True

    def predict(self) -> tuple[np.ndarray, np.ndarray]:
        """Return posterior mean and covariance in probit space.

        Returns:
            (mu_post, sigma_post) tuple
        """
        if not self._fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")
        return self.mu_post.copy(), self.sigma_post.copy()

    def sample_thompson(self, n_samples: int = 1) -> np.ndarray:
        """Draw correlated Thompson samples in [0, 1].

        Samples from the multivariate normal GP posterior, then
        applies probit link to get correlated probability samples.

        Args:
            n_samples: Number of sample vectors to draw

        Returns:
            Array of shape (n_samples, n_sources) with values in [0, 1]
        """
        if not self._fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")

        # Sample from multivariate normal
        z = np.random.multivariate_normal(
            self.mu_post, self.sigma_post, size=n_samples
        )

        # Apply probit link: Phi(z) -> [0, 1]
        theta = norm_cdf(z)

        return theta

    def optimize_hyperparameters(
        self,
        features: list[SourceFeatures],
        alphas: np.ndarray,
        betas: np.ndarray,
    ) -> dict:
        """Optimize kernel hyperparameters via marginal log-likelihood.

        Uses L-BFGS-B with log-transformed parameters to ensure positivity.

        Args:
            features: Source features
            alphas: Beta alpha parameters
            betas: Beta beta parameters

        Returns:
            Dict with optimized hyperparameters and final log-likelihood
        """
        n = len(features)
        if n < 3:
            return {"converged": False, "reason": "too_few_sources"}

        X = np.array([f.features for f in features])
        types = [f.source_type for f in features]

        # Moment matching observations
        mu_obs = np.zeros(n)
        sigma2_obs = np.zeros(n)
        for i in range(n):
            a, b = alphas[i], betas[i]
            p = np.clip(a / (a + b), 0.01, 0.99)
            mu_obs[i] = norm_ppf(p)
            phi_val = norm.pdf(mu_obs[i])
            if phi_val > 1e-10:
                sigma2_obs[i] = 1.0 / (phi_val ** 2 * (a + b + 1))
            else:
                sigma2_obs[i] = 100.0

        def neg_log_marginal_likelihood(log_params):
            ls, sv, cv, nv = np.exp(log_params)

            # Save and set hyperparams temporarily
            old = (self.length_scale, self.signal_variance,
                   self.category_variance, self.noise_variance)
            self.length_scale = ls
            self.signal_variance = sv
            self.category_variance = cv
            self.noise_variance = nv

            K = self.compute_kernel_matrix(X, types)

            # Restore
            (self.length_scale, self.signal_variance,
             self.category_variance, self.noise_variance) = old

            # Marginal likelihood: y ~ N(0, K + diag(sigma2_obs))
            C = K + np.diag(sigma2_obs)
            C += 1e-6 * np.eye(n)  # Jitter

            try:
                L = np.linalg.cholesky(C)
                alpha = np.linalg.solve(L.T, np.linalg.solve(L, mu_obs))
                log_det = 2 * np.sum(np.log(np.diag(L)))
                nll = 0.5 * (mu_obs @ alpha + log_det + n * np.log(2 * np.pi))
                return nll
            except np.linalg.LinAlgError:
                return 1e10

        # Initial log-params
        x0 = np.log([
            self.length_scale, self.signal_variance,
            self.category_variance, self.noise_variance,
        ])

        # Bounds in log-space: exp(-3) ~ 0.05, exp(3) ~ 20
        bounds = [(-3, 3)] * 4

        result = optimize.minimize(
            neg_log_marginal_likelihood,
            x0,
            method="L-BFGS-B",
            bounds=bounds,
        )

        if result.success:
            optimized = np.exp(result.x)
            self.length_scale = optimized[0]
            self.signal_variance = optimized[1]
            self.category_variance = optimized[2]
            self.noise_variance = optimized[3]

        return {
            "converged": result.success,
            "log_likelihood": -result.fun if result.success else None,
            "hyperparameters": {
                "length_scale": self.length_scale,
                "signal_variance": self.signal_variance,
                "category_variance": self.category_variance,
                "noise_variance": self.noise_variance,
            },
        }

    def to_dict(self) -> dict:
        """Serialize model state (hyperparameters only, not posterior)."""
        return {
            "hyperparameters": {
                "length_scale": self.length_scale,
                "signal_variance": self.signal_variance,
                "category_variance": self.category_variance,
                "noise_variance": self.noise_variance,
            },
            "sources": self.sources,
            "fitted": self._fitted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GPSourceModel":
        """Deserialize from dict. Posterior must be recomputed via fit()."""
        hp = data.get("hyperparameters", {})
        model = cls(
            length_scale=hp.get("length_scale", 1.0),
            signal_variance=hp.get("signal_variance", 1.0),
            category_variance=hp.get("category_variance", 0.3),
            noise_variance=hp.get("noise_variance", 0.1),
        )
        model.sources = data.get("sources")
        return model
