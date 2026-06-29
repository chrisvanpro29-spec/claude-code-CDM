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


def _form_raw(att_self: float, def_opp: float, mid_self: float, mid_opp: float,
              ref: Reference) -> float:
    """Contribution centrée de la FORME au raw (avant tanh) : attaque vs défense
    adverse + différentiel de milieu. Le tanh/CLIP est appliqué une fois sur le
    raw combiné (forme + qualité)."""
    ref_att, ref_mid, ref_def = ref
    return ((att_self - ref_att) - (def_opp - ref_def)
            + config.MID_TILT_WEIGHT * ((mid_self - ref_mid) - (mid_opp - ref_mid)))


def adjusted_lambdas(lam_home: float, lam_away: float,
                     notes_home: TeamNotes | None, notes_away: TeamNotes | None,
                     ref: Reference | None = None,
                     qual_home: float | None = None, qual_away: float | None = None,
                     layer_on: bool | None = None) -> tuple[float, float, dict]:
    """Applique le tilt joueur aux λ. Retourne (λ_home, λ_away, info).

    Deux apports **séparables** derrière le MÊME interrupteur, chacun centré :
      - forme (notes équipe : attaque/milieu/défense vs adversaire, via `ref`) ;
      - qualité d'effectif (`qual_*`, scalaires déjà centrés/standardisés SoFIFA).
    On peut tourner forme seule (qual_* = None), qualité seule (notes_* = None),
    ou les deux — pour que l'ablation mesure chaque apport.

    - `layer_on` force l'état de l'interrupteur (sinon config.PLAYER_LAYER_ON).
      OFF => λ_ajusté == λ_base exactement (notes ET qualité neutralisées).
    - Aucune donnée (ni forme ni qualité) -> fallback équipe seule, signalé.
    - **Garde-fou anti-récidive** : si la forme s'applique (notes présentes) sans
      `ref`, on LÈVE une exception (pas de retombée silencieuse sur (0,0)).
    - Borne : tanh + CLIP => |variation de λ| <= w·CLIP quels que soient les poids
      internes -> la couche incline le socle, ne le domine jamais.
    """
    on = config.PLAYER_LAYER_ON if layer_on is None else layer_on
    info = {"layer_applied": False, "reason": "", "tilt_home": 0.0, "tilt_away": 0.0,
            "form_applied": False, "quality_applied": False}

    if not on:
        info["reason"] = "interrupteur OFF"
        return lam_home, lam_away, info

    form_ok = notes_home is not None and notes_away is not None
    qual_ok = qual_home is not None and qual_away is not None
    if not form_ok and not qual_ok:
        info["reason"] = "couverture insuffisante (ni forme ni qualité) -> fallback équipe seule"
        return lam_home, lam_away, info

    if form_ok and ref is None:
        raise ValueError(
            "adjusted_lambdas : `ref` est None alors que la forme s'applique. "
            "Calculer la référence ligue (league_reference) et la passer — "
            "aucune retombée silencieuse sur (0,0) n'est tolérée."
        )

    raw_home, raw_away = 0.0, 0.0
    if form_ok:
        raw_home += _form_raw(notes_home.attack, notes_away.defense,
                              notes_home.mid, notes_away.mid, ref)
        raw_away += _form_raw(notes_away.attack, notes_home.defense,
                              notes_away.mid, notes_home.mid, ref)
        info["form_applied"] = True
    if qual_ok:
        raw_home += config.QUALITY_TILT_WEIGHT * (qual_home - qual_away)
        raw_away += config.QUALITY_TILT_WEIGHT * (qual_away - qual_home)
        info["quality_applied"] = True

    tilt_home = config.PLAYER_TILT_CLIP * math.tanh(raw_home)
    tilt_away = config.PLAYER_TILT_CLIP * math.tanh(raw_away)

    w = config.PLAYER_TILT_WEIGHT
    lam_home_adj = lam_home * (1 + w * tilt_home)
    lam_away_adj = lam_away * (1 + w * tilt_away)

    parts = [p for p, ok in (("forme", info["form_applied"]),
                             ("qualité", info["quality_applied"])) if ok]
    info.update({"layer_applied": True, "tilt_home": tilt_home, "tilt_away": tilt_away,
                 "reason": "tilt appliqué (" + "+".join(parts) + ")"})
    return lam_home_adj, lam_away_adj, info
