"""Module 2 — Couche joueur live : la fonction-porte anti-fuite (brief §3).

`note_joueur(joueur, date_ref, store)` est le SEUL chemin d'accès aux données
joueur. Elle filtre `matchs[date < date_ref]` EN DUR (strictement avant le coup
d'envoi prédit). La fuite doit être *impossible*, pas seulement évitée : tout
accès passe par `PlayerMatchStore.history(...)`, qui applique le filtre lui-même,
et `note_joueur` ne touche jamais aux lignes brutes autrement.

Important (brief §1.6) : pas de note fabriquée. Si le store est vide pour un
joueur, `note_joueur` renvoie None — la couche se désactivera pour ce match.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

import config
from . import league_strength

# Composantes brutes attendues (par match), toujours ramenées par 90 minutes.
# On NE consomme JAMAIS une note composite opaque (SofaScore…) : on reconstruit.
ATTACK_COMPONENTS = ["goals", "xg", "assists", "xa", "key_passes", "chances_created"]
MID_COMPONENTS = ["prog_passes", "key_passes", "recoveries", "pass_pct_pressure"]
DEF_COMPONENTS = ["tackles", "interceptions", "duels_won", "clearances", "xg_against"]
# Union (sans doublon) de toutes les composantes -> base de la standardisation.
ALL_COMPONENTS = list(dict.fromkeys(ATTACK_COMPONENTS + MID_COMPONENTS + DEF_COMPONENTS))

REQUIRED_COLS = {"player", "date", "competition", "is_national", "minutes"}


@dataclass
class PlayerNote:
    """Note brute d'un joueur à une `date_ref`, reconstruite depuis ses composantes."""
    player: str
    attack: float
    mid: float
    defense: float
    n_club: int          # nb de matchs club utilisés (<= CLUB_FORM_WINDOW)
    n_national: int      # nb de matchs sélection utilisés (<= NATIONAL_FORM_WINDOW)

    @property
    def n_matches(self) -> int:
        return self.n_club + self.n_national


class PlayerMatchStore:
    """Dépôt des journaux de matchs joueur. Unique surface d'accès aux données joueur.

    Vide par défaut dans cet environnement (sources FBref/Understat fragiles,
    auditées comme telles). Brancher un vrai jeu via `from_dataframe`.
    """

    def __init__(self, df: pd.DataFrame | None = None) -> None:
        if df is None:
            df = pd.DataFrame(columns=sorted(REQUIRED_COLS))
        missing = REQUIRED_COLS - set(df.columns)
        if missing and not df.empty:
            raise ValueError(f"PlayerMatchStore : colonnes manquantes {missing}")
        if not df.empty:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
        self._df = df
        # Audit anti-fuite : date la plus récente jamais renvoyée par history().
        self.max_date_served: dt.date | None = None

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> "PlayerMatchStore":
        return cls(df)

    def history(self, player: str, before: dt.date) -> pd.DataFrame:
        """Lignes du joueur STRICTEMENT antérieures à `before`. Filtre en dur ici.

        C'est le seul point qui lit les données joueur. Le filtre `< before` est
        appliqué *avant* tout retour, donc aucune ligne >= before ne peut sortir.
        """
        if self._df.empty:
            return self._df
        sub = self._df[(self._df["player"] == player) & (self._df["date"] < before)]
        if not sub.empty:
            served = sub["date"].max()
            if self.max_date_served is None or served > self.max_date_served:
                self.max_date_served = served
        return sub.sort_values("date")

    def population_before(self, cutoff: dt.date) -> pd.DataFrame:
        """Toutes les lignes (tous joueurs) STRICTEMENT avant `cutoff`.

        Utilisé UNIQUEMENT pour ajuster l'échelle de population du normalizer.
        Sans fuite : moyenne/écart-type d'une stat sont des propriétés de
        population, pas des infos sur le résultat d'un match — et tous les matchs
        de CDM étant >= cutoff, aucune donnée future n'entre dans l'échelle.
        """
        if self._df.empty:
            return self._df
        return self._df[self._df["date"] < cutoff]


def _component_per90(rows: pd.DataFrame, component: str) -> float:
    """Valeur par 90 min d'UNE composante, pondérée par la force de ligue."""
    if rows.empty or component not in rows.columns:
        return 0.0
    coef = rows["competition"].map(league_strength.strength).to_numpy()
    vals = pd.to_numeric(rows[component], errors="coerce").fillna(0.0).to_numpy()
    minutes = float(rows["minutes"].clip(lower=1).sum())
    return float((vals * coef).sum()) / minutes * 90.0 if minutes > 0 else 0.0


class ComponentNormalizer:
    """Échelle de population par composante (z-score) — correction 3.

    Stocke, par composante, la moyenne et l'écart-type des valeurs **par 90 min**
    sur la population de joueurs. Ajustée UNE SEULE fois sur les matchs
    `date < cutoff` (population pré-tournoi) -> sans fuite.
    """

    def __init__(self, means: dict[str, float], stds: dict[str, float]) -> None:
        self.means = means
        self.stds = stds

    @classmethod
    def fit(cls, store: PlayerMatchStore,
            cutoff: dt.date | None = None) -> "ComponentNormalizer":
        cutoff = cutoff or config.NORMALIZER_FIT_CUTOFF
        pop = store.population_before(cutoff)
        means: dict[str, float] = {}
        stds: dict[str, float] = {}
        if pop.empty:
            return cls({c: 0.0 for c in ALL_COMPONENTS}, {c: 0.0 for c in ALL_COMPONENTS})
        # 1 valeur par 90 min par joueur et par composante -> stats de population.
        per_player = {c: [] for c in ALL_COMPONENTS}
        for _, grp in pop.groupby("player"):
            for c in ALL_COMPONENTS:
                per_player[c].append(_component_per90(grp, c))
        for c in ALL_COMPONENTS:
            arr = pd.Series(per_player[c], dtype=float)
            means[c] = float(arr.mean()) if len(arr) else 0.0
            stds[c] = float(arr.std(ddof=0)) if len(arr) else 0.0
        return cls(means, stds)

    def z(self, component: str, value: float) -> float:
        """z-score d'une valeur. Écart-type nul -> 0 (pas de division par zéro, pas de NaN)."""
        std = self.stds.get(component, 0.0)
        if not std or std <= 0.0:
            return 0.0
        return (value - self.means.get(component, 0.0)) / std


# Normalizer « neutre » par défaut : tous les z = 0 (échelle non ajustée).
_IDENTITY_NORMALIZER = ComponentNormalizer({c: 0.0 for c in ALL_COMPONENTS},
                                           {c: 0.0 for c in ALL_COMPONENTS})


def _group_note(rows: pd.DataFrame, components: list[str],
                normalizer: ComponentNormalizer) -> float:
    """Note d'un groupe (attaque/milieu/défense) = Σ_c poids_c · signe_c · z_c.

    Chaque composante est standardisée (z-score) AVANT combinaison : la note
    mesure « qui est décisif », pas « qui touche le ballon ».
    """
    total = 0.0
    for c in components:
        if c not in rows.columns:
            continue
        val = _component_per90(rows, c)
        z = normalizer.z(c, val)
        weight = config.COMPONENT_WEIGHTS.get(c, 0.0)
        sign = -1.0 if c == "xg_against" else 1.0   # encaisser dégrade la défense
        total += weight * sign * z
    return total


def note_joueur(joueur: str, date_ref: dt.date, store: PlayerMatchStore,
                normalizer: ComponentNormalizer | None = None) -> PlayerNote | None:
    """Fonction-porte : 3 notes (attaque, milieu, défense) à `date_ref`, ou None.

    Fenêtre glissante : 20 derniers matchs de club + 10 derniers en sélection,
    tous antérieurs à `date_ref`. Les matchs CDM déjà joués entrent légalement au
    fil du tournoi (ils sont < date_ref du match suivant), jamais avant.

    `normalizer` fixe l'échelle (z-scores) ; à défaut, échelle neutre (z = 0).
    """
    normalizer = normalizer or _IDENTITY_NORMALIZER
    hist = store.history(joueur, date_ref)   # SEUL accès aux données joueur
    if hist.empty:
        return None  # pas de note fabriquée

    club = hist[~hist["is_national"].astype(bool)].tail(config.CLUB_FORM_WINDOW)
    national = hist[hist["is_national"].astype(bool)].tail(config.NATIONAL_FORM_WINDOW)
    used = pd.concat([club, national])
    if used.empty:
        return None

    return PlayerNote(
        player=joueur,
        attack=_group_note(used, ATTACK_COMPONENTS, normalizer),
        mid=_group_note(used, MID_COMPONENTS, normalizer),
        defense=_group_note(used, DEF_COMPONENTS, normalizer),
        n_club=len(club),
        n_national=len(national),
    )


# ---------------------------------------------------------------------------
# §3.4 shrinkage + §3.5 agrégation en 3 notes d'équipe
# ---------------------------------------------------------------------------

@dataclass
class SquadPlayer:
    """Un joueur du onze probable : poste + minutes attendues."""
    player: str
    position: str          # 'ATT' / 'MID' / 'DEF' / 'GK'
    expected_minutes: float


@dataclass
class TeamNotes:
    """3 notes d'équipe à une date, + couverture (nb de joueurs notés)."""
    attack: float
    mid: float
    defense: float
    n_players: int


def _shrink(value: float, n: int, prior: float) -> float:
    """James-Stein / empirical Bayes : tire `value` vers `prior`.

    Moins de matchs (n petit) => on tire plus fort vers la moyenne (moins de confiance).
    """
    k = config.SHRINKAGE_K
    if n <= 0:
        return prior
    alpha = n / (n + k)
    return alpha * value + (1 - alpha) * prior


def team_notes(squad: list[SquadPlayer], date_ref: dt.date, store: PlayerMatchStore,
               normalizer: ComponentNormalizer | None = None) -> TeamNotes | None:
    """Agrège les notes individuelles en 3 notes d'équipe à `date_ref`.

    - shrinkage de chaque note vers la moyenne de SON poste dans l'effectif ;
    - pondération par les minutes attendues (titulaires > remplaçants).
    Renvoie None si la couverture est insuffisante (brief §3.6 / §1.6 : pas de
    note fabriquée) -> le couplage retombera sur la force équipe seule.
    """
    notes: list[tuple[SquadPlayer, PlayerNote]] = []
    for sp in squad:
        pn = note_joueur(sp.player, date_ref, store, normalizer)
        if pn is not None:
            notes.append((sp, pn))

    if len(notes) < config.MIN_PLAYERS_FOR_LAYER:
        return None

    # Moyennes par poste (prior de shrinkage).
    def pos_mean(attr: str, pos: str) -> float:
        vals = [getattr(pn, attr) for sp, pn in notes if sp.position == pos]
        if vals:
            return float(sum(vals) / len(vals))
        allv = [getattr(pn, attr) for _, pn in notes]
        return float(sum(allv) / len(allv)) if allv else 0.0

    agg = {"attack": 0.0, "mid": 0.0, "defense": 0.0}
    total_min = sum(max(sp.expected_minutes, 0.0) for sp, _ in notes) or 1.0
    for sp, pn in notes:
        wmin = max(sp.expected_minutes, 0.0) / total_min
        for attr in agg:
            shrunk = _shrink(getattr(pn, attr), pn.n_matches, pos_mean(attr, sp.position))
            agg[attr] += wmin * shrunk

    return TeamNotes(attack=agg["attack"], mid=agg["mid"],
                     defense=agg["defense"], n_players=len(notes))
