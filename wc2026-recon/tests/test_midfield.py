"""Correction 2 — brancher la note de milieu dans le tilt.

Le milieu entre comme un différentiel **centré** entre les deux milieux, pondéré
par κ. On vérifie : dominer le milieu relève sa propre attaque ; milieux égaux =>
aucun effet milieu ; κ = 0 => comportement strictement identique à avant.
"""

from __future__ import annotations

import pytest

import config
from engine import coupling
from engine.player_form import TeamNotes

REF = (0.0, 0.0, 0.0)


def test_midfield_dominance_lifts_home():
    home = TeamNotes(attack=0.0, mid=1.0, defense=0.0, n_players=11)
    away = TeamNotes(attack=0.0, mid=-1.0, defense=0.0, n_players=11)
    _, _, info = coupling.adjusted_lambdas(1.5, 1.0, home, away, ref=REF, layer_on=True)
    assert info["tilt_home"] > info["tilt_away"]
    assert info["tilt_home"] > 0


def test_equal_midfields_contribute_nothing():
    # Milieux égaux (mais non nuls) -> même résultat qu'avec milieux à 0.
    h_eq = TeamNotes(attack=1.0, mid=5.0, defense=0.0, n_players=11)
    a_eq = TeamNotes(attack=0.0, mid=5.0, defense=0.0, n_players=11)
    h_0 = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)
    a_0 = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
    r_eq = coupling.adjusted_lambdas(1.5, 1.0, h_eq, a_eq, ref=REF, layer_on=True)
    r_0 = coupling.adjusted_lambdas(1.5, 1.0, h_0, a_0, ref=REF, layer_on=True)
    assert r_eq[0] == pytest.approx(r_0[0])
    assert r_eq[1] == pytest.approx(r_0[1])


def test_kappa_zero_is_regression_to_attack_defense_only(monkeypatch):
    monkeypatch.setattr(config, "MID_TILT_WEIGHT", 0.0)
    # Avec κ=0, un énorme différentiel de milieu ne doit RIEN changer.
    h_mid = TeamNotes(attack=1.0, mid=9.0, defense=0.0, n_players=11)
    a_mid = TeamNotes(attack=0.0, mid=-9.0, defense=0.0, n_players=11)
    h_no = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)
    a_no = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
    r_mid = coupling.adjusted_lambdas(1.5, 1.0, h_mid, a_mid, ref=REF, layer_on=True)
    r_no = coupling.adjusted_lambdas(1.5, 1.0, h_no, a_no, ref=REF, layer_on=True)
    assert r_mid[0] == pytest.approx(r_no[0])
    assert r_mid[1] == pytest.approx(r_no[1])
