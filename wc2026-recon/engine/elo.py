"""Elo recalculé depuis la source A — zéro dépendance externe (brief §2).

Sert de **feature de cohérence** et de contre-vérification, JAMAIS de source des
buts. Style « World Football Elo » : K-factor ajusté par l'écart de buts, bonus
terrain si match non neutre.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import config
from . import data


def _goal_diff_multiplier(goal_diff: int) -> float:
    """Ajustement K par marge de victoire (World Football Elo)."""
    if not config.ELO_GOAL_DIFF_SCALING:
        return 1.0
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8.0


def compute_elo(as_of: dt.date | None = None) -> dict[str, float]:
    """Rejoue tout l'historique joué (< as_of) et retourne le rating Elo courant par équipe."""
    cutoff = as_of or config.WC2026_START
    df = data.played(data.load_results())
    df = df[df["date"] < cutoff].sort_values("date")

    ratings: dict[str, float] = defaultdict(lambda: config.ELO_BASE)
    for r in df.itertuples(index=False):
        h, a = r.home_team, r.away_team
        rh, ra = ratings[h], ratings[a]
        # Avantage terrain : nul si match neutre.
        ha = 0.0 if getattr(r, "neutral", False) else config.ELO_HOME_ADV
        eh = 1.0 / (1.0 + 10 ** (-((rh + ha) - ra) / 400.0))
        ea = 1.0 - eh
        gd = int(r.home_score - r.away_score)
        if gd > 0:
            sh, sa = 1.0, 0.0
        elif gd < 0:
            sh, sa = 0.0, 1.0
        else:
            sh, sa = 0.5, 0.5
        k = config.ELO_K * _goal_diff_multiplier(gd)
        ratings[h] = rh + k * (sh - eh)
        ratings[a] = ra + k * (sa - ea)
    return dict(ratings)


def win_probability(rating_home: float, rating_away: float, neutral: bool = True) -> float:
    """Proba (cohérence) que 'home' gagne selon l'Elo. Pour contre-vérification seulement."""
    ha = 0.0 if neutral else config.ELO_HOME_ADV
    return 1.0 / (1.0 + 10 ** (-((rating_home + ha) - rating_away) / 400.0))
