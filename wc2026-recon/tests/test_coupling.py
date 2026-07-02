"""Tests du couplage (brief §4) : interrupteur, borne du tilt, fallback.

Prouve que l'ablation OFF/ON n'est PAS un no-op par construction : avec des notes,
les λ bougent ; sans notes ou OFF, ils sont strictement inchangés ; et l'effet
reste borné (la couche incline, ne domine jamais).
"""

from __future__ import annotations

import config
from engine import coupling
from engine.player_form import TeamNotes


GOOD = TeamNotes(attack=2.0, mid=1.0, defense=2.0, n_players=11)
WEAK = TeamNotes(attack=-2.0, mid=-1.0, defense=-2.0, n_players=11)
REF = (0.0, 0.0, 0.0)   # = league_reference([GOOD, WEAK])


def test_switch_off_is_identity():
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, GOOD, WEAK, layer_on=False)
    assert (lh, la) == (1.5, 1.0)
    assert not info["layer_applied"]


def test_missing_notes_fall_back():
    # Notes manquantes -> fallback AVANT toute exigence de ref (pas de raise).
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, GOOD, layer_on=True)
    assert (lh, la) == (1.5, 1.0)
    assert "fallback" in info["reason"]


def test_notes_move_lambdas():
    base_h, base_a = 1.5, 1.0
    lh, la, info = coupling.adjusted_lambdas(base_h, base_a, GOOD, WEAK,
                                             ref=REF, layer_on=True)
    assert info["layer_applied"]
    # Forte attaque vs faible défense adverse -> tilt home positif -> λ_home monte.
    assert lh > base_h
    assert lh != base_h and la != base_a


def test_tilt_is_bounded():
    """|variation de λ| <= w * CLIP, quelles que soient les notes (anti-domination)."""
    base = 1.5
    bound = config.PLAYER_TILT_WEIGHT * config.PLAYER_TILT_CLIP
    for nh, na in [(GOOD, WEAK), (WEAK, GOOD), (GOOD, GOOD)]:
        lh, la, _ = coupling.adjusted_lambdas(base, base, nh, na, ref=REF, layer_on=True)
        assert abs(lh - base) <= base * bound + 1e-9
        assert abs(la - base) <= base * bound + 1e-9


def test_normal_form_is_neutral():
    """Notes égales à la référence -> tilt ~ 0 -> λ quasi inchangés (forme normale)."""
    neutral = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
    lh, la, _ = coupling.adjusted_lambdas(1.5, 1.0, neutral, neutral,
                                          ref=(0.0, 0.0, 0.0), layer_on=True)
    assert abs(lh - 1.5) < 1e-9
    assert abs(la - 1.0) < 1e-9
