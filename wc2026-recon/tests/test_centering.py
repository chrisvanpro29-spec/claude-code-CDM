"""Correction 1 — centrer le tilt sur la vraie moyenne (référence ligue), pas zéro.

Une équipe simplement *bonne* (qualité déjà dans α/β) ne doit pas être récompensée
deux fois : seul l'écart à la moyenne compte. On vérifie aussi le garde-fou
anti-récidive : appliquer la couche sans `ref` lève une exception (plus de
retombée silencieuse sur (0,0)).
"""

from __future__ import annotations

import pytest

from engine import coupling
from engine.player_form import TeamNotes


A = TeamNotes(attack=1.0, mid=0.0, defense=1.0, n_players=11)
B = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
C = TeamNotes(attack=-1.0, mid=0.0, defense=-1.0, n_players=11)
REF = coupling.league_reference([A, B, C])   # -> (0, 0, 0)


def test_reference_is_the_mean():
    assert REF == pytest.approx((0.0, 0.0, 0.0))


def test_team_at_reference_is_neutral():
    at_ref = TeamNotes(attack=REF[0], mid=REF[1], defense=REF[2], n_players=11)
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, at_ref, at_ref,
                                             ref=REF, layer_on=True)
    assert info["layer_applied"]
    assert lh == pytest.approx(1.5)
    assert la == pytest.approx(1.0)


def test_above_reference_tilts_up():
    home = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)   # att > ref
    away = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)   # def == ref
    _, _, info = coupling.adjusted_lambdas(1.5, 1.0, home, away, ref=REF, layer_on=True)
    assert info["tilt_home"] > 0


def test_symmetric_teams_opposite_tilts():
    home = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)
    away = TeamNotes(attack=-1.0, mid=0.0, defense=0.0, n_players=11)
    _, _, info = coupling.adjusted_lambdas(1.5, 1.0, home, away, ref=REF, layer_on=True)
    assert info["tilt_home"] == pytest.approx(-info["tilt_away"])


def test_missing_reference_raises():
    with pytest.raises(ValueError):
        coupling.adjusted_lambdas(1.5, 1.0, A, B, ref=None, layer_on=True)


def test_empty_reference_is_neutral_tuple():
    assert coupling.league_reference([None, None]) == (0.0, 0.0, 0.0)
