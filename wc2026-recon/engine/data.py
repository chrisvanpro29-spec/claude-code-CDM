"""Chargement des résultats internationaux (source A) + découpe train / test CDM 2026.

Source unique de buts : `results.csv` (source A, auditée `trusted`). Le gel
out-of-sample (config.WC2026_START) sépare l'historique de fit du jeu de test.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd

import config
from audit.paths import raw_dir

RESULTS_CSV = raw_dir("A_international_results") / "results.csv"


@lru_cache(maxsize=1)
def load_results() -> pd.DataFrame:
    """Charge results.csv mis en cache par le probe de la source A.

    Colonnes : date, home_team, away_team, home_score, away_score, tournament,
    city, country, neutral.
    """
    if not RESULTS_CSV.exists():
        raise FileNotFoundError(
            f"{RESULTS_CSV} absent. Lancer d'abord `python recon.py` (probe source A) "
            "pour mettre le CSV en cache."
        )
    df = pd.read_csv(RESULTS_CSV, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def played(df: pd.DataFrame) -> pd.DataFrame:
    """Matchs réellement joués (scores non nuls)."""
    return df.dropna(subset=["home_score", "away_score"]).copy()


def training_matches(as_of: dt.date | None = None) -> pd.DataFrame:
    """Historique de fit : matchs joués, STRICTEMENT avant le gel, dans la fenêtre.

    `as_of` permet au walk-forward de faire entrer légalement les matchs CDM déjà
    joués au fil du tournoi (fenêtre glissante), tout en gardant la baseline gelée
    avant WC2026_START. Par défaut = gel.
    """
    df = played(load_results())
    cutoff = as_of or config.WC2026_START
    start = dt.date(cutoff.year - config.TRAIN_WINDOW_YEARS, cutoff.month, cutoff.day)
    mask = (df["date"] < cutoff) & (df["date"] >= start)
    return df[mask].sort_values("date").reset_index(drop=True)


def wc2026_matches(played_only: bool = False) -> pd.DataFrame:
    """Matchs de la CDM 2026 (label tournoi + date >= gel). Le jeu de test."""
    df = load_results()
    mask = (df["tournament"] == config.WC2026_TOURNAMENT_LABEL) & (df["date"] >= config.WC2026_START)
    wc = df[mask].sort_values("date").reset_index(drop=True)
    if played_only:
        wc = played(wc).reset_index(drop=True)
    return wc
