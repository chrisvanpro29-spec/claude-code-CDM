"""Coefficients de force des ligues (brief §3.3).

Un but / xG ne vaut pas la même chose selon le contexte : UCL ≠ Ligue 2 ≠ match
contre une sélection faible. Sans cet ajustement, 20 matchs de contextes
incomparables produisent du bruit. Ces coefficients sont des hyperparamètres
**pré-enregistrés** (ils relèvent de config, on ne les optimise pas sur le test).

Échelle : 1.0 = référence « grand championnat ». < 1 = contexte plus faible
(un but y compte moins) ; > 1 = contexte plus relevé.
"""

from __future__ import annotations

# Table figée. La clé est un identifiant de compétition normalisé (minuscules).
LEAGUE_STRENGTH: dict[str, float] = {
    # Coupes européennes de clubs
    "uefa champions league": 1.25,
    "uefa europa league": 1.05,
    "uefa europa conference league": 0.95,
    # Grands championnats nationaux
    "premier league": 1.20,
    "la liga": 1.15,
    "serie a": 1.12,
    "bundesliga": 1.12,
    "ligue 1": 1.05,
    # Deuxième cercle
    "primeira liga": 0.90,
    "eredivisie": 0.90,
    "championship": 0.85,
    "mls": 0.80,
    "liga mx": 0.80,
    "saudi pro league": 0.80,
    # Internationaux (compétitions de sélections — contexte fort)
    "fifa world cup": 1.30,
    "uefa euro": 1.20,
    "copa america": 1.15,
    "uefa nations league": 1.05,
    "africa cup of nations": 1.00,
    "fifa world cup qualification": 0.95,
    "friendly": 0.70,
}

# Coefficient par défaut pour une compétition non répertoriée (championnat moyen).
DEFAULT_STRENGTH = 0.75


def strength(competition: str | None) -> float:
    """Coefficient de force pour une compétition (insensible à la casse)."""
    if not competition:
        return DEFAULT_STRENGTH
    return LEAGUE_STRENGTH.get(competition.strip().lower(), DEFAULT_STRENGTH)
