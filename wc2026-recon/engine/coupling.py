"""Couplage — comment la couche joueur entre dans les λ (brief §4 + corrections 1 & 2).

Tilt **borné**, **centré sur la vraie moyenne** (référence ligue, pas zéro), et
incluant le **différentiel de milieu**. Forme « normale » => tilt ≈ 0. La couche
*incline* le socle, ne le *domine* jamais :

    raw_home  = (att_home - ref_att) - (def_away - ref_def)
                + κ · ((mid_home - ref_mid) - (mid_away - ref_mid))
    tilt_home = CLIP · tanh(raw_home)
    λ_ajusté  = λ_base · (1 + w · tilt)

Le terme `ref_mid` s'annule dans la différence -> le milieu entre comme l'écart
**centré** entre les deux milieux, pondéré par κ. Anti-double-comptage : la qualité
absolue est déjà dans α/β, on ne récompense que l'écart à la forme attendue.

Interrupteur `PLAYER_LAYER_ON`. OFF => λ_ajusté == λ_base exactement.
"""

from __future__ import annotations

import math

import config
from .player_form import TeamNotes

# Type de la référence ligue : (moyenne_attaque, moyenne_milieu, moyenne_défense).
Reference = tuple[float, float, float]


def league_reference(team_notes_list: list[TeamNotes | None]) -> Reference:
    """Moyenne des notes d'équipe sur toutes les équipes ayant une couverture.

    Centre du tilt (correction 1). Calculée à une `date_ref` donnée à partir des
    notes produites par `team_notes(...)` (donc via `note_joueur` -> sans fuite).
    """
    notes = [n for n in team_notes_list if n is not None]
    if not notes:
        return (0.0, 0.0, 0.0)
    n = len(notes)
    return (
        sum(t.attack for t in notes) / n,
        sum(t.mid for t in notes) / n,
        sum(t.defense for t in notes) / n,
    )


def _tilt(att_self: float, def_opp: float, mid_self: float, mid_opp: float,
          ref: Reference) -> float:
    """Tilt centré d'une équipe : attaque vs défense adverse + différentiel de milieu."""
    ref_att, ref_mid, ref_def = ref
    raw = ((att_self - ref_att) - (def_opp - ref_def)
           + config.MID_TILT_WEIGHT * ((mid_self - ref_mid) - (mid_opp - ref_mid)))
    return config.PLAYER_TILT_CLIP * math.tanh(raw)


def adjusted_lambdas(lam_home: float, lam_away: float,
                     notes_home: TeamNotes | None, notes_away: TeamNotes | None,
                     ref: Reference | None = None,
                     layer_on: bool | None = None) -> tuple[float, float, dict]:
    """Applique le tilt joueur aux λ. Retourne (λ_home, λ_away, info).

    - `layer_on` force l'état de l'interrupteur (sinon config.PLAYER_LAYER_ON).
    - Si une des deux équipes n'a pas de notes (couverture insuffisante), la
      couche est neutralisée pour CE match -> fallback équipe seule, signalé.
    - **Garde-fou anti-récidive (correction 1)** : dès qu'on s'apprête à appliquer
      le tilt (notes présentes) sans `ref`, on LÈVE une exception. Plus de
      retombée silencieuse sur (0,0) : le bug devient impossible, pas seulement évité.
    """
    on = config.PLAYER_LAYER_ON if layer_on is None else layer_on
    info = {"layer_applied": False, "reason": "", "tilt_home": 0.0, "tilt_away": 0.0}

    if not on:
        info["reason"] = "interrupteur OFF"
        return lam_home, lam_away, info
    if notes_home is None or notes_away is None:
        info["reason"] = "couverture joueur insuffisante -> fallback équipe seule"
        return lam_home, lam_away, info

    if ref is None:
        raise ValueError(
            "adjusted_lambdas : `ref` est None alors que la couche s'applique. "
            "Calculer la référence ligue (league_reference) et la passer — "
            "aucune retombée silencieuse sur (0,0) n'est tolérée."
        )

    tilt_home = _tilt(notes_home.attack, notes_away.defense,
                      notes_home.mid, notes_away.mid, ref)
    tilt_away = _tilt(notes_away.attack, notes_home.defense,
                      notes_away.mid, notes_home.mid, ref)

    w = config.PLAYER_TILT_WEIGHT
    lam_home_adj = lam_home * (1 + w * tilt_home)
    lam_away_adj = lam_away * (1 + w * tilt_away)

    info.update({"layer_applied": True, "tilt_home": tilt_home, "tilt_away": tilt_away,
                 "reason": "tilt joueur appliqué"})
    return lam_home_adj, lam_away_adj, info
