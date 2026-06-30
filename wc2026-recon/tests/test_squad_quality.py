"""Tests de la qualité d'effectif (centrage SoFIFA) et de son branchement couplage.

Couvre : centrage/standardisation (moyenne -> 0, au-dessus -> +, symétrie -> opposés,
écart-type nul gardé) ; et le 4e tilt côté coupling (OFF neutralise, qualité seule
fonctionne, qualité bornée, séparabilité forme/qualité).
"""

from __future__ import annotations

import pandas as pd
import pytest

import config
from engine import squad_quality as sq
from engine import coupling
from engine.player_form import TeamNotes

REF = (0.0, 0.0, 0.0)


# --- Ciblage des sélections nationales (pas des clubs) ---------------------

def test_targets_national_teams_not_clubs(monkeypatch):
    """fetch_team_quality doit cibler la ligue des sélections, pas les clubs."""
    captured = {}

    def fake_ratings(leagues, versions="latest"):
        captured["leagues"] = leagues
        # DataFrame façon SoFIFA national-teams (index = sélections).
        return pd.DataFrame({"overall": [85, 84, 83]},
                            index=["France", "Germany", "Brazil"])

    monkeypatch.setattr(sq, "_sofifa_team_ratings", fake_ratings)
    out = sq.fetch_team_quality()

    # cible la ligue des sélections nationales, jamais une ligue de clubs
    assert sq.SOFIFA_NATIONAL_LEAGUE_KEY in captured["leagues"]
    assert not (set(captured["leagues"]) & sq.KNOWN_CLUB_LEAGUE_KEYS)
    # la sortie contient des sélections, pas des clubs
    assert {"France", "Germany", "Brazil"} <= set(out)
    assert not ({"Manchester City", "Real Madrid", "Bayern Munich"} & set(out))


def test_parser_extracts_named_teams():
    df = pd.DataFrame({"overall": [85, 83]}, index=["France", "Germany"])
    assert sq._team_ratings_to_dict(df) == {"France": 85.0, "Germany": 83.0}


def test_register_national_league_adds_key():
    from soccerdata import _config as sdcfg
    sq._register_national_league()
    assert sq.SOFIFA_NATIONAL_LEAGUE_KEY in sdcfg.LEAGUE_DICT
    assert sq.SOFIFA_NATIONAL_LEAGUE_KEY not in sq.KNOWN_CLUB_LEAGUE_KEYS


# --- Centrage qualité -----------------------------------------------------

def test_center_mean_is_zero():
    centered = sq.center_quality({"A": 80, "B": 82, "C": 78})  # moyenne = 80 = A
    assert centered["A"] == pytest.approx(0.0)          # A == moyenne
    assert centered["B"] > 0 and centered["C"] < 0      # ordre conservé


def test_center_symmetry_opposite():
    centered = sq.center_quality({"hi": 85, "lo": 75})  # symétriques autour de 80
    assert centered["hi"] == pytest.approx(-centered["lo"])


def test_center_zero_std_no_div_zero():
    centered = sq.center_quality({"A": 80, "B": 80})
    assert centered == {"A": 0.0, "B": 0.0}


def test_center_empty():
    assert sq.center_quality({}) == {}


# --- Branchement couplage (qualité) ---------------------------------------

def test_quality_off_is_identity():
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=2.0, qual_away=-2.0, layer_on=False)
    assert (lh, la) == (1.5, 1.0) and not info["layer_applied"]


def test_quality_only_tilts_without_form():
    # Séparabilité : qualité seule (notes=None) incline quand même les λ.
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=1.5, qual_away=-1.5, layer_on=True)
    assert info["layer_applied"] and info["quality_applied"] and not info["form_applied"]
    assert lh > 1.5 and la < 1.0


def test_equal_quality_is_neutral():
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=0.7, qual_away=0.7, layer_on=True)
    assert info["tilt_home"] == pytest.approx(0.0)
    assert lh == pytest.approx(1.5) and la == pytest.approx(1.0)


def test_quality_bounded():
    """Même une qualité énorme reste bornée par w·CLIP (ne domine jamais)."""
    base = 1.5
    bound = config.PLAYER_TILT_WEIGHT * config.PLAYER_TILT_CLIP
    lh, la, _ = coupling.adjusted_lambdas(base, base, None, None,
                                          qual_home=100.0, qual_away=-100.0, layer_on=True)
    assert abs(lh - base) <= base * bound + 1e-9
    assert abs(la - base) <= base * bound + 1e-9


def test_form_and_quality_separable_and_additive():
    notes_h = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)
    notes_a = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
    # forme seule
    _, _, f = coupling.adjusted_lambdas(1.5, 1.0, notes_h, notes_a, ref=REF, layer_on=True)
    # forme + qualité (qualité home supérieure) -> tilt_home encore plus haut
    _, _, fq = coupling.adjusted_lambdas(1.5, 1.0, notes_h, notes_a, ref=REF,
                                         qual_home=1.0, qual_away=-1.0, layer_on=True)
    assert f["form_applied"] and not f["quality_applied"]
    assert fq["form_applied"] and fq["quality_applied"]
    assert fq["tilt_home"] > f["tilt_home"]
