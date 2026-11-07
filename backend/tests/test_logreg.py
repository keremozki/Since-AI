"""The from-scratch logistic regression must follow the course formulas and match scikit-learn."""
import numpy as np

from app.confidence import new_model
from app.logreg import NumpyLogReg, compute_cost, compute_gradient, sigmoid


def data(seed=0, m=80):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(m, 4)) * [1, 10, 0.1, 100]
    y = (X[:, 0] + X[:, 1] / 10 + rng.normal(0, 0.8, m) > 0.5).astype(float)
    return X, y


def test_sigmoid_values():
    assert sigmoid(np.array([0.0]))[0] == 0.5
    assert abs(sigmoid(np.array([2.0]))[0] - 0.8808) < 1e-4
    assert sigmoid(np.array([-1000.0]))[0] >= 0  # no overflow


def test_cost_matches_hand_calculation():
    X, y, w = np.array([[1.0], [2.0]]), np.array([1.0, 0.0]), np.array([0.5])
    f = sigmoid(X @ w)
    expected = -np.mean(y * np.log(f) + (1 - y) * np.log(1 - f)) + 2 / 4 * 0.25
    assert abs(compute_cost(X, y, w, 0.0, lam=2) - expected) < 1e-12


def test_gradient_matches_numerical_derivative():
    X, y = data()
    rng = np.random.default_rng(1)
    w, b, s = rng.normal(size=4) * 0.01, 0.1, rng.uniform(0.5, 2, len(y))
    dw, db = compute_gradient(X, y, w, b, lam=2, s=s)
    eps = 1e-6
    for j in range(4):
        e = np.zeros(4)
        e[j] = eps
        numeric = (compute_cost(X, y, w + e, b, 2, s) - compute_cost(X, y, w - e, b, 2, s)) / (2 * eps)
        assert abs(numeric - dw[j]) < 1e-5
    assert abs((compute_cost(X, y, w, b + eps, 2, s) - compute_cost(X, y, w, b - eps, 2, s)) / (2 * eps) - db) < 1e-5


def test_cost_goes_down_during_training():
    X, y = data()
    history = NumpyLogReg().fit(X, y).cost_history
    assert history[-1] < history[0]
    assert all(b <= a + 1e-12 for a, b in zip(history, history[1:]))


def test_matches_scikit_learn_with_c_equal_one_over_lambda():
    X, y = data(seed=3)
    ours = NumpyLogReg(C=0.5).fit(X, y).predict_proba(X)[:, 1]
    theirs = new_model().fit(X, y).predict_proba(X)[:, 1]
    assert np.max(np.abs(ours - theirs)) < 1e-3
