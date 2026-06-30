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


# --- Reconstruction par joueur (note d'effectif reconstruite, pas lue) ------

from engine.player_form import SquadPlayer


def _squad(*names_minutes):
    return [SquadPlayer(player=n, position="MID", expected_minutes=m)
            for n, m in names_minutes]


def test_player_ratings_parser():
    df = pd.DataFrame({"overall": [88, 84]}, index=["Mbappé", "Griezmann"])
    assert sq.player_ratings_to_dict(df) == {"Mbappé": 88.0, "Griezmann": 84.0}


def test_aggregate_minutes_weighted():
    squads = {"France": _squad(("Mbappé", 90), ("Sub", 0))}
    ratings = {"Mbappé": 90.0, "Sub": 70.0}
    out, _ = sq.aggregate_squad_quality(squads, ratings, min_players=1)
    # titulaire (90 min) domine le remplaçant (0 min) -> proche de 90, pas 80
    assert out["France"] == pytest.approx(90.0)


def test_aggregate_skips_undercovered_nation():
    squads = {"Tuvalu": _squad(("X", 90))}                 # 1 seul joueur connu
    ratings = {"X": 70.0}
    out, _ = sq.aggregate_squad_quality(squads, ratings, min_players=6)
    assert "Tuvalu" not in out                              # couverture insuffisante -> omise


def test_aggregate_logs_unmatched():
    squads = {"France": _squad(("Mbappé", 90), ("Inconnu", 90))}
    ratings = {"Mbappé": 90.0}
    out, unmatched = sq.aggregate_squad_quality(squads, ratings, min_players=1)
    assert any("Inconnu" in u for u in unmatched)           # non-apparié loggé, jamais deviné


def test_reconstruct_then_center_uses_players_not_team(monkeypatch):
    """Bout en bout (sans réseau) : note d'effectif reconstruite depuis les joueurs."""
    squads = {
        "France":  _squad(*[(f"FR{i}", 90) for i in range(8)]),
        "Germany": _squad(*[(f"DE{i}", 90) for i in range(8)]),
    }
    ratings = {**{f"FR{i}": 88.0 for i in range(8)},        # France plus forte
               **{f"DE{i}": 80.0 for i in range(8)}}

    def fake_player_ratings(leagues=None, versions="latest"):
        return ratings
    monkeypatch.setattr(sq, "fetch_player_ratings", fake_player_ratings)

    centered = sq.centered_quality(squads)
    assert set(centered) == {"France", "Germany"}           # des sélections, pas des clubs
    assert centered["France"] > 0 > centered["Germany"]     # France au-dessus de la moyenne
    assert centered["France"] == pytest.approx(-centered["Germany"])  # symétrie (2 équipes)


def test_centered_quality_empty_without_squads():
    assert sq.centered_quality({}) == {}                    # pas d'effectif -> pas de note fabriquée


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
