"""Couplage — comment la couche joueur entre dans les λ (brief §4).

Tilt **borné**, centré sur l'écart à la forme attendue (anti-double-comptage : la
qualité absolue est déjà dans α/β). Forme « normale » => tilt ≈ 0. La couche
*incline* le socle, ne le *domine* jamais :

    tilt = f(note_attaque_équipe  vs  note_defense_adverse)   # centré
    λ_ajusté = λ_base · (1 + w · tilt)

Interrupteur `PLAYER_LAYER_ON`. OFF => λ_ajusté == λ_base exactement.
"""

from __future__ import annotations

import math

import config
from .player_form import TeamNotes


def _centered_tilt(att_team: float, def_opponent: float,
                   ref_att: float, ref_def: float) -> float:
    """Écart centré (forme) entre l'attaque d'une équipe et la défense adverse.

    `ref_*` = niveau « normal » attendu (centre). Quand att/def collent à la
    référence, le tilt est ~0. Borné dans [-CLIP, +CLIP] par une tanh douce.
    """
    # def_opponent et ref_def sont des notes où plus haut = meilleure défense ;
    # une bonne défense adverse réduit le tilt offensif -> on soustrait.
    raw = (att_team - ref_att) - (def_opponent - ref_def)
    # tanh : réponse douce et naturellement bornée à |1|, puis échelle CLIP.
    return config.PLAYER_TILT_CLIP * math.tanh(raw)


def adjusted_lambdas(lam_home: float, lam_away: float,
                     notes_home: TeamNotes | None, notes_away: TeamNotes | None,
                     ref: tuple[float, float] | None = None,
                     layer_on: bool | None = None) -> tuple[float, float, dict]:
    """Applique le tilt joueur aux λ. Retourne (λ_home, λ_away, info).

    - `layer_on` force l'état de l'interrupteur (sinon config.PLAYER_LAYER_ON).
    - Si une des deux équipes n'a pas de notes (couverture insuffisante), la
      couche est neutralisée pour CE match -> fallback équipe seule, signalé.
    """
    on = config.PLAYER_LAYER_ON if layer_on is None else layer_on
    info = {"layer_applied": False, "reason": "", "tilt_home": 0.0, "tilt_away": 0.0}

    if not on:
        info["reason"] = "interrupteur OFF"
        return lam_home, lam_away, info
    if notes_home is None or notes_away is None:
        info["reason"] = "couverture joueur insuffisante -> fallback équipe seule"
        return lam_home, lam_away, info

    ref_att, ref_def = ref if ref is not None else (0.0, 0.0)
    tilt_home = _centered_tilt(notes_home.attack, notes_away.defense, ref_att, ref_def)
    tilt_away = _centered_tilt(notes_away.attack, notes_home.defense, ref_att, ref_def)

    w = config.PLAYER_TILT_WEIGHT
    lam_home_adj = lam_home * (1 + w * tilt_home)
    lam_away_adj = lam_away * (1 + w * tilt_away)

    info.update({"layer_applied": True, "tilt_home": tilt_home, "tilt_away": tilt_away,
                 "reason": "tilt joueur appliqué"})
    return lam_home_adj, lam_away_adj, info
