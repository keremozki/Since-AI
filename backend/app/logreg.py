"""Logistic regression from scratch, with the formulas from Andrew Ng's Machine Learning course (C1 W2-W3).

    z-score scaling     x_j := (x_j - mu_j) / sigma_j
    model               f_wb(x) = g(w . x + b),   g(z) = 1 / (1 + e^-z)          (sigmoid)
    cost (log loss)     J(w,b) = -(1/m) sum_i s_i [y_i log f_i + (1 - y_i) log(1 - f_i)]
                                 + (lambda / 2m) sum_j w_j^2                       (L2 regularisation)
    gradient            dJ/dw_j = (1/m) sum_i s_i (f_i - y_i) x_ij + (lambda/m) w_j
                        dJ/db   = (1/m) sum_i s_i (f_i - y_i)
    gradient descent    w := w - alpha dJ/dw,   b := b - alpha dJ/db

s_i is the class weight ("balanced": m / (2 * count of y_i's class)), so a rare class counts as much as
a common one. scikit-learn minimises C * sum s_i loss_i + 1/2 |w|^2, which has the same minimum when
lambda = 1 / C. So C = 0.5 here is lambda = 2, and this class matches
make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced")).
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))


def balanced_weights(y: np.ndarray) -> np.ndarray:
    m = len(y)
    counts = {c: np.sum(y == c) for c in (0, 1)}
    return np.array([m / (2 * counts[c]) for c in y], dtype=float)


def compute_cost(X: np.ndarray, y: np.ndarray, w: np.ndarray, b: float, lam: float = 0.0,
                 s: np.ndarray | None = None) -> float:
    m = len(y)
    s = np.ones(m) if s is None else s
    f = np.clip(sigmoid(X @ w + b), 1e-15, 1 - 1e-15)
    loss = -(y * np.log(f) + (1 - y) * np.log(1 - f))
    return float(np.sum(s * loss) / m + lam / (2 * m) * np.sum(w ** 2))


def compute_gradient(X: np.ndarray, y: np.ndarray, w: np.ndarray, b: float, lam: float = 0.0,
                     s: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    m = len(y)
    s = np.ones(m) if s is None else s
    err = s * (sigmoid(X @ w + b) - y)
    return X.T @ err / m + lam / m * w, float(np.sum(err) / m)


def gradient_descent(X, y, w, b, alpha, iters, lam=0.0, s=None, tol=1e-10):
    """Returns w, b and the cost history (the learning curve of the optimiser)."""
    history = []
    for i in range(iters):
        dw, db = compute_gradient(X, y, w, b, lam, s)
        w, b = w - alpha * dw, b - alpha * db
        if i % 50 == 0 or i == iters - 1:
            history.append(compute_cost(X, y, w, b, lam, s))
        if max(np.max(np.abs(dw)), abs(db)) < tol:
            history.append(compute_cost(X, y, w, b, lam, s))
            break
    return w, b, history


class NumpyLogReg(ClassifierMixin, BaseEstimator):
    """Drop-in for the scikit-learn pipeline: fit, predict_proba, and weights on scaled features."""

    def __init__(self, C: float = 0.5, class_weight: str | None = "balanced", alpha: float = 0.5, iters: int = 20000):
        self.C, self.class_weight, self.alpha, self.iters = C, class_weight, alpha, iters

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NumpyLogReg":
        X, y = np.asarray(X, float), np.asarray(y, float)
        self.lam = 1.0 / self.C
        self.classes_ = np.array([0, 1])
        self.mu = X.mean(axis=0)
        self.sigma = X.std(axis=0)
        self.sigma[self.sigma == 0] = 1.0  # a constant feature stays 0 after scaling
        Xs = (X - self.mu) / self.sigma
        s = balanced_weights(y) if self.class_weight == "balanced" else None
        self.w, self.b, self.cost_history = gradient_descent(Xs, y, np.zeros(X.shape[1]), 0.0, self.alpha, self.iters,
                                                             self.lam, s)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = sigmoid(((np.asarray(X, float) - self.mu) / self.sigma) @ self.w + self.b)
        return np.column_stack([1 - p, p])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def coef_(self) -> np.ndarray:
        return self.w[None, :]

    def __getitem__(self, index):
        # Lets code written for the pipeline (model[-1].coef_) read the weights.
        return self
