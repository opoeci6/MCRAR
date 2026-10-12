"""Deterministic heads and calibration; export only portable numeric arrays."""

from __future__ import annotations

import numpy as np

from mcrar.ml.tagging.runtime import Tagger, sigmoid, softmax


def make_tagger(
    label_set: str, kind: str, labels: list[str], arrays: dict, method: str = "head"
) -> Tagger:
    return Tagger(
        label_set,
        kind,
        labels,
        "",
        method,
        {k: np.asarray(v, dtype=np.float32) for k, v in arrays.items()},
    )


def calibrate(tagger: Tagger, x: np.ndarray, y: np.ndarray) -> Tagger:
    from scipy.optimize import minimize, minimize_scalar

    logits = tagger.scores(x).astype(np.float64)
    if "reference_mean" in tagger.arrays:
        raise ValueError("unsupervised entries must never be calibrated with labels")
    if tagger.kind == "single_label":

        def loss(log_t: float) -> float:
            p = softmax(logits / np.exp(log_t))
            return float(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-12)).mean())

        fit = minimize_scalar(loss, bounds=(-5, 5), method="bounded")
        scale, offset = np.array([np.exp(-fit.x)]), np.zeros(1)
    elif tagger.kind == "multi_label":
        scale, offset = [], []
        for i in range(logits.shape[1]):
            target = y[:, i]
            if target.min() == target.max():
                # Smoothed intercept, including all-negative validation tags.
                prevalence = (target.sum() + 1) / (len(target) + 2)
                scale.append(0.0)
                offset.append(np.log(prevalence / (1 - prevalence)))
                continue

            def loss(
                params: np.ndarray, column=logits[:, i], target=target
            ) -> tuple[float, np.ndarray]:
                a, b = params
                z = column * a + b
                residual = sigmoid(z) - target
                value = np.mean(np.logaddexp(0, z) - target * z) + 1e-6 * a * a
                grad = [np.mean(residual * column) + 2e-6 * a, residual.mean()]
                return float(value), np.array(grad)

            fit = minimize(
                loss, [1.0, -2.0], jac=True, method="L-BFGS-B", bounds=[(0, None), (None, None)]
            )
            scale.append(fit.x[0])
            offset.append(fit.x[1])
        scale, offset = np.array(scale), np.array(offset)
    else:
        # Affine validation calibration for a continuous value, clipped at inference.
        design = np.column_stack([logits[:, 0], np.ones(len(logits))])
        params = np.linalg.lstsq(design, y[:, 0], rcond=None)[0]
        scale, offset = params[:1], params[1:]
    arrays = {
        **tagger.arrays,
        "scale": scale.astype(np.float32),
        "offset": offset.astype(np.float32),
    }
    return Tagger(tagger.label_set, tagger.kind, tagger.labels, "", tagger.method, arrays)


def train_logreg(
    label_set: str, kind: str, labels: list[str], x: np.ndarray, y: np.ndarray, *, seed: int = 0
) -> Tagger:
    from sklearn.linear_model import LogisticRegression, Ridge

    if kind == "regression":
        model = Ridge(alpha=1)
        model.fit(x, y)
        weight = model.coef_.reshape(len(labels), x.shape[1]).T
        bias = np.atleast_1d(model.intercept_)
    elif kind == "single_label":
        if set(y.tolist()) != set(range(len(labels))):
            raise ValueError("training split must contain every genre")
        model = LogisticRegression(C=10, max_iter=1000, random_state=seed)
        model.fit(x, y)
        weight, bias = model.coef_.T, model.intercept_
        if len(labels) == 2:
            # sklearn's binary decision score has one column; two logits preserve its sigmoid.
            weight = np.column_stack([np.zeros(x.shape[1]), weight[:, 0]])
            bias = np.r_[0, bias]
    else:
        columns, biases = [], []
        for i in range(len(labels)):
            if np.unique(y[:, i]).size == 1:
                p = (y[:, i].sum() + 1) / (len(y) + 2)
                columns.append(np.zeros(x.shape[1]))
                biases.append(np.log(p / (1 - p)))
            else:
                model = LogisticRegression(
                    C=10, max_iter=1000, random_state=seed, class_weight="balanced"
                )
                model.fit(x, y[:, i])
                columns.append(model.coef_[0])
                biases.append(model.intercept_[0])
        weight, bias = np.stack(columns, axis=1), np.array(biases)
    return make_tagger(label_set, kind, labels, {"weight": weight, "bias": bias})


def train_mlp(
    label_set: str,
    kind: str,
    labels: list[str],
    x: np.ndarray,
    y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int = 0,
    hidden: int = 256,
    epochs: int = 100,
    patience: int = 12,
    batch_size: int = 256,
    dropout: float = 0.2,
) -> Tagger:
    # Numpy training keeps synthetic/default tests independent of torch. The same arrays are
    # used at runtime, with Adam, dropout and early stopping on the *official* validation set.
    if not 0 <= dropout < 1 or min(hidden, epochs, patience, batch_size) < 1:
        raise ValueError("invalid MLP training parameters")
    rng = np.random.default_rng(seed)
    weights = [
        rng.normal(0, np.sqrt(2 / x.shape[1]), (x.shape[1], hidden)).astype(np.float32),
        np.zeros(hidden, dtype=np.float32),
        rng.normal(0, np.sqrt(2 / hidden), (hidden, len(labels))).astype(np.float32),
        np.zeros(len(labels), dtype=np.float32),
    ]
    first = [np.zeros_like(w) for w in weights]
    second = [np.zeros_like(w) for w in weights]
    target = np.eye(len(labels), dtype=np.float32)[y] if kind == "single_label" else y
    valid = (
        np.eye(len(labels), dtype=np.float32)[validation_y]
        if kind == "single_label"
        else validation_y
    )
    positive_weight = (
        np.clip((len(y) - y.sum(axis=0)) / np.maximum(y.sum(axis=0), 1), 1, 20)
        if kind == "multi_label"
        else np.ones(len(labels))
    )
    best, best_loss, stale, step = [w.copy() for w in weights], float("inf"), 0, 0
    for _ in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            batch, truth = x[idx], target[idx]
            w1, b1, w2, b2 = weights
            pre = batch @ w1 + b1
            hidden_x = np.maximum(pre, 0)
            mask = (rng.random(hidden_x.shape) >= dropout).astype(np.float32) / (1 - dropout)
            hidden_x *= mask
            output = hidden_x @ w2 + b2
            if kind == "single_label":
                delta = (softmax(output) - truth) / len(idx)
            elif kind == "multi_label":
                delta = (
                    (sigmoid(output) - truth)
                    * (1 + truth * (positive_weight - 1))
                    / (len(idx) * len(labels))
                )
            else:
                delta = 2 * (output - truth) / (len(idx) * len(labels))
            hidden_delta = (delta @ w2.T) * mask * (pre > 0)
            gradients = [
                batch.T @ hidden_delta + 1e-5 * w1,
                hidden_delta.sum(axis=0),
                hidden_x.T @ delta + 1e-5 * w2,
                delta.sum(axis=0),
            ]
            step += 1
            for i, grad in enumerate(gradients):
                first[i] = 0.9 * first[i] + 0.1 * grad
                second[i] = 0.999 * second[i] + 0.001 * grad * grad
                weights[i] -= (
                    0.001
                    * (first[i] / (1 - 0.9**step))
                    / (np.sqrt(second[i] / (1 - 0.999**step)) + 1e-8)
                )
        output = np.maximum(validation_x @ weights[0] + weights[1], 0) @ weights[2] + weights[3]
        if kind == "single_label":
            loss = -np.mean(np.sum(valid * np.log(np.maximum(softmax(output), 1e-12)), axis=1))
        elif kind == "multi_label":
            loss = np.mean(np.logaddexp(0, output) - valid * output)
        else:
            loss = np.mean((output - valid) ** 2)
        if loss < best_loss - 1e-6:
            best, best_loss, stale = [w.copy() for w in weights], float(loss), 0
        else:
            stale += 1
            if stale >= patience:
                break
    return make_tagger(
        label_set,
        kind,
        labels,
        dict(zip(["hidden_weight", "hidden_bias", "weight", "bias"], best, strict=True)),
    )
