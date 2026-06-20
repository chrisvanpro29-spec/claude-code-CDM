"""Métriques de calibration pré-enregistrées (brief §6.3) : Brier, log-loss, reliability.

Convention 1X2 : vecteur [p_home, p_draw, p_away], résultat encodé 0/1/2.
"""

from __future__ import annotations

import numpy as np

import config

EPS = 1e-12


def brier_multiclass(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Brier multi-classe = moyenne des sum_k (p_k - 1{y=k})^2. Plus petit = mieux."""
    probs = np.asarray(probs, dtype=float)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(outcomes)), outcomes] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def log_loss_multiclass(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Log-loss multi-classe = -moyenne log p(résultat réel)."""
    probs = np.clip(np.asarray(probs, dtype=float), EPS, 1.0)
    p_true = probs[np.arange(len(outcomes)), outcomes]
    return float(-np.mean(np.log(p_true)))


def brier_binary(probs: np.ndarray, outcomes: np.ndarray) -> float:
    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    return float(np.mean((probs - outcomes) ** 2))


def reliability_curve(probs: np.ndarray, hits: np.ndarray,
                      n_bins: int = config.RELIABILITY_BINS):
    """Courbe de fiabilité : (proba moyenne prédite, fréquence observée, effectif) par bin.

    `probs` et `hits` sont aplatis (one-vs-rest sur les 3 classes -> 3 points/match).
    """
    probs = np.asarray(probs, dtype=float)
    hits = np.asarray(hits, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, n_bins - 1)
    mean_pred, freq_obs, counts = [], [], []
    for b in range(n_bins):
        sel = idx == b
        if sel.any():
            mean_pred.append(float(probs[sel].mean()))
            freq_obs.append(float(hits[sel].mean()))
            counts.append(int(sel.sum()))
        else:
            mean_pred.append(np.nan); freq_obs.append(np.nan); counts.append(0)
    return np.array(mean_pred), np.array(freq_obs), np.array(counts)


def flatten_ovr(probs: np.ndarray, outcomes: np.ndarray):
    """Aplatit le 1X2 en points one-vs-rest pour le reliability diagram."""
    probs = np.asarray(probs, dtype=float)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(outcomes)), outcomes] = 1.0
    return probs.ravel(), onehot.ravel()
