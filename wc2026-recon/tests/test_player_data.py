"""Tests d'extraction FBref (transformations pures, données synthétiques).

Couvre : aplatissement du MultiIndex, normalisation par 90 (division par zéro
gardée), ajustement par la force de ligue, et émission des lignes store au schéma
attendu par PlayerMatchStore.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from engine import player_data as pdata
from engine import league_strength


def test_flatten_multiindex_to_simple_names():
    cols = pd.MultiIndex.from_tuples([
        ("Standard", "Gls"), ("Standard", "xG"), ("Unnamed: 5_level_0", "90s"),
    ])
    df = pd.DataFrame([[3, 2.5, 10.0]], columns=cols)
    flat = pdata.flatten_columns(df)
    assert list(flat.columns) == ["Gls", "xG", "90s"]


def test_per90_basic_and_div_zero():
    # 18 buts en 10×90s -> 1.8/90.
    assert pdata.per90(18, 10) == pytest.approx(1.8)
    assert pdata.per90(5, 0) == 0.0       # division par zéro gardée
    assert pdata.per90(5, None) == 0.0


def test_per90_series_guards_zero():
    out = pdata.per90_series(pd.Series([18, 5, 9]), pd.Series([10, 0, 3]))
    assert list(out.round(3)) == [1.8, 0.0, 3.0]


def test_league_adjust_orders_by_strength():
    # même stat brute, deux contextes -> UCL > friendly.
    ucl = pdata.league_adjust(1.0, "UEFA Champions League")
    fr = pdata.league_adjust(1.0, "Friendly")
    assert ucl > fr
    assert ucl == pytest.approx(league_strength.strength("UEFA Champions League"))


def test_to_store_rows_schema_and_minutes():
    merged = pd.DataFrame([
        {"player": "Mbappé", "Gls": 18, "xG": 15.0, "Ast": 6, "xAG": 5.0,
         "KP": 40, "SCA": 60, "PrgP": 80, "Recov": 50, "Cmp%": 84.0,
         "Tkl": 10, "Int": 12, "Won": 20, "Clr": 8, "90s": 10.0},
        {"player": "NoMinutes", "Gls": 0, "90s": 0.0},   # ignoré (0 minute)
    ])
    rows = pdata.to_store_rows(merged, competition="Ligue 1", is_national=False,
                               date=dt.date(2026, 6, 1))
    assert len(rows) == 1                          # le joueur sans minute est écarté
    r = rows[0]
    # schéma attendu par PlayerMatchStore
    for k in ("player", "date", "competition", "is_national", "minutes"):
        assert k in r
    assert r["minutes"] == pytest.approx(900.0)    # 10 × 90
    # totaux bruts mappés vers les noms canoniques (le /90 est fait par player_form)
    assert r["goals"] == 18 and r["xg"] == 15.0 and r["key_passes"] == 40
    assert r["duels_won"] == 20                     # 'Won' -> duels_won
    assert "xg_against" not in r                    # jamais fabriqué


def test_real_fbref_duplicate_names_no_ambiguous_series():
    """Régression : FBref répète 'Gls'/'xG' (total ET /90) -> libellés dupliqués.

    Avant le fix, `components_per90_adjusted` levait
    « ValueError: The truth value of a Series is ambiguous » sur ces colonnes.
    """
    cols = pd.MultiIndex.from_tuples([
        ("Unnamed: 0_level_0", "player"),
        ("Performance", "Gls"), ("Per 90 Minutes", "Gls"),     # doublon -> garder le total
        ("Expected", "xG"), ("Per 90 Minutes", "xG"),          # doublon -> garder le total
        ("Playing Time", "90s"),
        ("Tackles", "Tkl"), ("Int", "Int"), ("Pass Types", "KP"),
    ])
    raw = pd.DataFrame([
        ["Dembélé", 18, 1.8, 15.0, 1.5, 10.0, 9, 12, 30],
        ["Reserve", 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0],           # 0 min -> ignoré
    ], columns=cols)

    flat = pdata.flatten_columns(raw)
    assert list(flat.columns).count("Gls") == 1                # dédupliqué
    assert list(flat.columns).count("xG") == 1

    rows = pdata.to_store_rows(flat, "Ligue 1", False, dt.date(2026, 6, 1))
    assert len(rows) == 1
    assert rows[0]["goals"] == 18 and rows[0]["xg"] == 15.0    # le TOTAL, pas le /90
    assert rows[0]["minutes"] == pytest.approx(900.0)

    # le chemin qui levait l'exception doit désormais passer
    view = pdata.components_per90_adjusted(rows)
    coef = league_strength.strength("Ligue 1")
    assert view[0]["goals"] == pytest.approx(1.8 * coef)       # 18/10 = 1.8, ajusté ligue


def test_store_rows_consumable_by_player_form():
    """Les lignes produites passent telles quelles dans note_joueur (pas de réécriture)."""
    from engine.player_form import PlayerMatchStore, ComponentNormalizer, note_joueur
    merged = pd.DataFrame([
        {"player": "P", "Gls": 9, "xG": 9.0, "KP": 18, "90s": 9.0,
         "Tkl": 9, "Int": 9, "PrgP": 18, "Recov": 9, "Cmp%": 80.0,
         "Ast": 3, "xAG": 3.0, "SCA": 27, "Won": 9, "Clr": 9},
    ])
    rows = pdata.to_store_rows(merged, "Premier League", False, dt.date(2026, 5, 1))
    store = PlayerMatchStore.from_dataframe(pd.DataFrame(rows))
    norm = ComponentNormalizer.fit(store, cutoff=dt.date(2026, 6, 11))
    note = note_joueur("P", dt.date(2026, 6, 11), store, norm)
    assert note is not None and note.n_club == 1
