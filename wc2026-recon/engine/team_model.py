"""Module 1 — Moteur équipe (Dixon-Coles), fit MLE + décroissance temporelle.

Chaque équipe i : force d'attaque α_i et « faiblesse défensive » β_i (convention
du brief : λ_i = exp(μ + α_i + β_j + γ·home), donc β_j élevé => j encaisse plus).
Estimation par maximum de vraisemblance pondéré exp(-ξ·Δt). Sortie : matrice de
scores P(x,y) => 1X2, over/under, score exact.

Traçabilité (brief §1.1) : proba <- λ <- (μ, α, β, γ, ρ) <- matchs pondérés. Pas
de boîte noire.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

import config
from . import data, elo as elo_mod


def _pool_rare_teams(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Replie les équipes peu vues sur OTHER ; retourne (df réécrit, liste équipes)."""
    counts = pd.concat([df["home_team"], df["away_team"]]).value_counts()
    keep = set(counts[counts >= config.MIN_MATCHES_PER_TEAM].index)
    df = df.copy()
    df["home_team"] = df["home_team"].where(df["home_team"].isin(keep), config.OTHER_TEAM)
    df["away_team"] = df["away_team"].where(df["away_team"].isin(keep), config.OTHER_TEAM)
    teams = sorted(set(df["home_team"]) | set(df["away_team"]))
    return df, teams


def _dc_tau(x, y, lam, mu, rho):
    """Terme de correction Dixon-Coles sur les petits scores (vectorisé).

    Conservé comme référence lisible de la correction τ ; l'optimiseur et
    `score_matrix` l'inlinent pour partager les calculs intermédiaires.
    """
    t = np.ones_like(lam, dtype=float)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t = np.where(m00, 1.0 - lam * mu * rho, t)
    t = np.where(m01, 1.0 + lam * rho, t)
    t = np.where(m10, 1.0 + mu * rho, t)
    t = np.where(m11, 1.0 - rho, t)
    return t


@dataclass
class FitResult:
    success: bool
    nll: float
    n_matches: int
    n_teams: int


class DixonColesModel:
    """Modèle Dixon-Coles avec time-decay. Gelé : aucun match CDM 2026 dans le fit."""

    def __init__(self) -> None:
        self.teams: list[str] = []
        self.idx: dict[str, int] = {}
        self.attack: np.ndarray | None = None
        self.defense: np.ndarray | None = None
        self.mu: float = config.DC_INTERCEPT_INIT
        self.gamma: float = config.DC_HOME_ADV_INIT
        self.rho: float = config.DC_RHO_INIT
        self.fit_result: FitResult | None = None
        self._as_of: dt.date | None = None

    # --- fit ----------------------------------------------------------------

    def fit(self, as_of: dt.date | None = None, verbose: bool = False) -> "DixonColesModel":
        self._as_of = as_of or config.WC2026_START
        raw = data.training_matches(as_of=self._as_of)
        df, teams = _pool_rare_teams(raw)
        self.teams = teams
        self.idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)

        hi = df["home_team"].map(self.idx).to_numpy()
        ai = df["away_team"].map(self.idx).to_numpy()
        x = df["home_score"].to_numpy(dtype=int)
        y = df["away_score"].to_numpy(dtype=int)
        home_flag = np.where(df["neutral"].fillna(False).to_numpy(), 0.0, 1.0)

        # Poids time-decay (référence = gel).
        ref = self._as_of
        dt_days = np.array([(ref - d).days for d in df["date"]], dtype=float)
        w = np.exp(-config.XI * dt_days)

        # Init via Elo (cohérence + convergence).
        ratings = elo_mod.compute_elo(as_of=self._as_of)
        mean_elo = np.mean(list(ratings.values())) if ratings else config.ELO_BASE
        a0 = np.array([(ratings.get(t, mean_elo) - mean_elo) / 400.0 * 0.5 for t in teams])
        a0 -= a0.mean()
        d0 = -a0.copy()  # bonne attaque ~ bonne défense -> β faible

        p0 = np.concatenate([a0, d0, [config.DC_INTERCEPT_INIT,
                                      config.DC_HOME_ADV_INIT, config.DC_RHO_INIT]])

        b = config.DC_PARAM_BOUND
        bounds = ([(-b, b)] * n + [(-b, b)] * n +
                  [config.DC_INTERCEPT_BOUNDS, config.DC_HOME_ADV_BOUNDS, config.DC_RHO_BOUNDS])

        def unpack(p):
            return p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1], p[2 * n + 2]

        def objective(p):
            """NLL pondérée + gradient analytique (1 passe O(matchs))."""
            att, dfn, mu, gamma, rho = unpack(p)
            log_lam = mu + att[hi] + dfn[ai] + gamma * home_flag
            log_mu_ = mu + att[ai] + dfn[hi]
            lam = np.exp(log_lam)
            muv = np.exp(log_mu_)

            # tau et ses dérivées (vectorisées par catégorie de petit score).
            m00 = (x == 0) & (y == 0)
            m01 = (x == 0) & (y == 1)
            m10 = (x == 1) & (y == 0)
            m11 = (x == 1) & (y == 1)
            tau = np.ones_like(lam)
            tau = np.where(m00, 1.0 - lam * muv * rho, tau)
            tau = np.where(m01, 1.0 + lam * rho, tau)
            tau = np.where(m10, 1.0 + muv * rho, tau)
            tau = np.where(m11, 1.0 - rho, tau)
            tau = np.clip(tau, 1e-10, None)

            dtau_dlam = np.where(m00, -muv * rho, np.where(m01, rho, 0.0))     # ∂τ/∂λ1
            dtau_dmu = np.where(m00, -lam * rho, np.where(m10, rho, 0.0))      # ∂τ/∂λ2
            dtau_drho = np.where(m00, -lam * muv, np.where(m01, lam,
                        np.where(m10, muv, np.where(m11, -1.0, 0.0))))         # ∂τ/∂ρ

            ll = np.log(tau) + x * log_lam - lam + y * log_mu_ - muv
            pen = config.DC_IDENTIFIABILITY_PENALTY * (att.mean() ** 2 + dfn.mean() ** 2)
            f = -np.sum(w * ll) + pen

            # d ll / d logλ1 et d logλ2 (chaîne via λ = exp(logλ)).
            g1 = (x - lam) + (lam / tau) * dtau_dlam
            g2 = (y - muv) + (muv / tau) * dtau_dmu
            gr = dtau_drho / tau

            wg1, wg2 = w * g1, w * g2
            grad_att = -(np.bincount(hi, wg1, n) + np.bincount(ai, wg2, n))
            grad_dfn = -(np.bincount(ai, wg1, n) + np.bincount(hi, wg2, n))
            # gradient de la pénalité d'identifiabilité.
            grad_att += config.DC_IDENTIFIABILITY_PENALTY * 2 * att.mean() / n
            grad_dfn += config.DC_IDENTIFIABILITY_PENALTY * 2 * dfn.mean() / n
            grad_mu = -np.sum(wg1 + wg2)
            grad_gamma = -np.sum(wg1 * home_flag)
            grad_rho = -np.sum(w * gr)

            grad = np.concatenate([grad_att, grad_dfn, [grad_mu, grad_gamma, grad_rho]])
            return f, grad

        res = minimize(objective, p0, method="L-BFGS-B", jac=True, bounds=bounds,
                       options={"maxiter": config.DC_OPTIMIZER_MAXITER, "disp": verbose})

        att, dfn, mu, gamma, rho = unpack(res.x)
        # Recentrage final (identifiabilité propre).
        att = att - att.mean()
        dfn = dfn - dfn.mean()
        self.attack, self.defense = att, dfn
        self.mu, self.gamma, self.rho = float(mu), float(gamma), float(rho)
        self.fit_result = FitResult(bool(res.success), float(res.fun), len(df), n)
        if verbose:
            print(f"[DC] fit: {len(df)} matchs, {n} équipes, "
                  f"nll={res.fun:.1f}, success={res.success}, "
                  f"mu={mu:.3f} gamma={gamma:.3f} rho={rho:.3f}")
        return self

    # --- prédiction ---------------------------------------------------------

    def _team_params(self, team: str) -> tuple[float, float]:
        i = self.idx.get(team, self.idx.get(config.OTHER_TEAM))
        if i is None:
            return 0.0, 0.0
        return float(self.attack[i]), float(self.defense[i])

    def lambdas(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        """λ attendus (buts) pour (home, away). Avantage terrain si non neutre."""
        ah, bh = self._team_params(home)
        aa, ba = self._team_params(away)
        hf = 0.0 if neutral else 1.0
        lam_h = np.exp(self.mu + ah + ba + self.gamma * hf)
        lam_a = np.exp(self.mu + aa + bh)
        return float(lam_h), float(lam_a)

    def score_matrix(self, lam_h: float, lam_a: float) -> np.ndarray:
        """Matrice P(x,y) avec correction Dixon-Coles sur les petits scores, normalisée."""
        k = config.DC_MAX_GOALS
        px = poisson.pmf(np.arange(k + 1), lam_h)
        py = poisson.pmf(np.arange(k + 1), lam_a)
        m = np.outer(px, py)
        rho = self.rho
        m[0, 0] *= 1.0 - lam_h * lam_a * rho
        m[0, 1] *= 1.0 + lam_h * rho
        m[1, 0] *= 1.0 + lam_a * rho
        m[1, 1] *= 1.0 - rho
        m = np.clip(m, 0.0, None)
        s = m.sum()
        return m / s if s > 0 else m

    def match_probabilities(self, home: str, away: str, neutral: bool = True,
                            lambdas: tuple[float, float] | None = None) -> dict:
        """1X2, over/under, score exact le plus probable, à partir de la matrice de scores."""
        lam_h, lam_a = lambdas if lambdas is not None else self.lambdas(home, away, neutral)
        m = self.score_matrix(lam_h, lam_a)
        idx = np.indices(m.shape)
        home_win = float(m[idx[0] > idx[1]].sum())
        draw = float(np.trace(m))
        away_win = float(m[idx[0] < idx[1]].sum())
        totals = idx[0] + idx[1]
        over = {line: float(m[totals > line].sum()) for line in config.OVER_UNDER_LINES}
        best = np.unravel_index(np.argmax(m), m.shape)
        return {
            "lambda_home": lam_h,
            "lambda_away": lam_a,
            "p_home": home_win,
            "p_draw": draw,
            "p_away": away_win,
            "over": over,
            "score_matrix": m,
            "most_likely_score": (int(best[0]), int(best[1])),
        }
