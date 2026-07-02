"""Schéma de l'enregistrement d'audit, identique pour toutes les sources.

La grille est volontairement figée : chaque probe remplit EXACTEMENT ces champs,
ce qui garantit un audit comparable d'une source à l'autre. Le champ `trust` est
un *résultat calculé par les tests*, jamais un préjugé d'entrée.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


class Trust:
    """Verdicts de fiabilité possibles (calculés, pas assignés d'avance)."""

    TRUSTED = "trusted"          # a passé les tests de réalisme/cohérence
    CONDITIONAL = "conditional"  # marche, mais avec réserves documentées
    UNVERIFIED = "unverified"    # non vérifiable dans ce run (accès, clé, lib…)
    FAILED = "failed"            # échoue au réalisme ou à la cohérence croisée

    ALL = (TRUSTED, CONDITIONAL, UNVERIFIED, FAILED)


# Granularités reconnues (couche de la donnée).
GRANULARITIES = ("team", "match", "player", "event", "odds", "unknown")


@dataclass
class AuditRecord:
    """Un enregistrement d'audit par source. Tous les champs de la grille §3."""

    source: str
    access_ok: bool = False
    auth_required: bool = False
    rate_limit: str = "unknown"
    granularity: str = "unknown"
    schema: list[str] = field(default_factory=list)
    completeness: str = "unknown"   # % de valeurs manquantes sur les champs clés
    freshness: str = "unknown"      # date la plus récente ; inclut la CDM live ?
    realism: str = "unknown"        # sanity checks
    coverage: str = "unknown"       # couvre-t-il les 48 équipes / leurs joueurs ?
    cost_to_scale: str = "unknown"  # plafond gratuit, point de rupture
    trust: str = Trust.UNVERIFIED
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    # --- helpers de remplissage ---------------------------------------------

    def note(self, msg: str) -> None:
        """Ajoute une observation libre (piège détecté, réserve, etc.)."""
        self.notes.append(msg)

    def fail(self, exc: BaseException) -> "AuditRecord":
        """Consigne une exception sans interrompre le run."""
        self.error = f"{type(exc).__name__}: {exc}"
        self.access_ok = False
        if self.trust == Trust.UNVERIFIED:
            # Un échec d'accès laisse la source non vérifiable, pas 'failed' :
            # 'failed' est réservé à une donnée qui ment (réalisme/cohérence).
            self.trust = Trust.UNVERIFIED
        return self

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
