"""Qualité d'effectif (SoFIFA) — 4e tilt centré (brief §2).

Note d'effectif **reconstruite à partir des joueurs**, PAS lue directement :
`SoFIFA.read_team_ratings`/`read_leagues` n'expose pas les sélections nationales
(soccerdata ne connaît que les championnats de clubs). On passe donc par les notes
FIFA individuelles (`SoFIFA.read_player_ratings`) puis on **agrège par sélection**
— moyenne des notes des joueurs de l'effectif, pondérée par les minutes attendues
(les titulaires pèsent plus). Cela colle d'ailleurs à l'esprit du projet : on
reconstruit la note à partir des composantes, jamais une note d'équipe opaque.

On **centre** ensuite (z-score sur la population des sélections) : c'est l'écart à
la normale qui compte, jamais l'absolu — la qualité de fond est déjà dans α/β du
modèle de base (anti-double-comptage). Sortie : un scalaire centré/borné par
sélection, branché comme tilt via `coupling.adjusted_lambdas(qual_home=…, …)`.

Limite assumée : SoFIFA `read_player_ratings` ne porte que les joueurs des grands
championnats -> riche pour les favoris, pauvre pour les petites nations (repli
couche équipe). Mapping par nom = fragile, non-appariés loggés, jamais devinés.

Alternative documentée (non implémentée v1) : valeur marché Transfermarkt via
scraper dédié (fragile + ToS), même traitement centré, si explicitement souhaitée.
"""

from __future__ import annotations

import statistics

# Nb minimal de joueurs d'un effectif retrouvés dans SoFIFA pour oser une note.
MIN_PLAYERS_FOR_QUALITY = 6

# Libellés possibles de la colonne de note globale renvoyée par read_player_ratings.
_RATING_COL_CANDIDATES = ("overall", "overall_rating", "Overall rating", "OVR", "ovr")


def center_quality(ratings: dict[str, float]) -> dict[str, float]:
    """Centre et standardise les notes d'effectif (z-score sur la population).

    - sélection à la moyenne -> 0 ;
    - au-dessus -> positif, en-dessous -> négatif ;
    - écart-type nul (toutes égales) -> 0 partout (pas de division par zéro).

    Le z-score borne naturellement l'échelle (~ordre 1), comparable aux notes de
    forme, pour que `QUALITY_TILT_WEIGHT` reste un poids interprétable.
    """
    if not ratings:
        return {}
    vals = list(ratings.values())
    mean = statistics.fmean(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    if std <= 0:
        return {team: 0.0 for team in ratings}
    return {team: (v - mean) / std for team, v in ratings.items()}


# ---------------------------------------------------------------------------
# Reconstruction par joueur (cœur testable, sans réseau)
# ---------------------------------------------------------------------------

def player_ratings_to_dict(df, rating_col: str | None = None) -> dict[str, float]:
    """Parser pur : DataFrame `read_player_ratings` -> {nom_joueur: note_overall}.

    `df` est indexé (ou colonne) par nom de joueur, avec une colonne de note globale.
    """
    col = rating_col
    if col is None:
        for cand in _RATING_COL_CANDIDATES:
            if cand in df.columns:
                col = cand
                break
    if col is None:
        numeric = df.select_dtypes("number")
        if numeric.empty:
            return {}
        col = numeric.columns[0]

    names = (df.index.get_level_values(-1) if hasattr(df.index, "get_level_values")
             else df.index)
    out: dict[str, float] = {}
    for name, val in zip(names, df[col].tolist()):
        try:
            out[str(name)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def aggregate_squad_quality(squads: dict, player_ratings: dict[str, float],
                            min_players: int = MIN_PLAYERS_FOR_QUALITY
                            ) -> tuple[dict[str, float], list[str]]:
    """Agrège les notes joueur par sélection (moyenne pondérée par les minutes).

    `squads` : {sélection: [SquadPlayer(player, position, expected_minutes)]}.
    Les noms (Wikipédia) sont recalés sur ceux de `player_ratings` (SoFIFA) via
    `squads.reconcile_names` : correspondance exacte après normalisation, puis
    approchée à seuil élevé — jamais devinée. Retourne ({sélection: note},
    non_appariés) ; une sélection dont trop peu de joueurs sont retrouvés est
    OMISE (couverture insuffisante -> la couche retombera sur la force équipe
    seule). Aucune note fabriquée.
    """
    from .squads import reconcile_names  # import tardif : évite un cycle au chargement

    out: dict[str, float] = {}
    unmatched: list[str] = []
    for nation, squad in squads.items():
        names = [getattr(sp, "player", None) for sp in squad]
        matched, not_found = reconcile_names([n for n in names if n], player_ratings)
        unmatched.extend(f"{nation}:{n}" for n in not_found)

        pairs = []  # (note, poids)
        for sp in squad:
            player = getattr(sp, "player", None)
            rating_name = matched.get(player)
            if rating_name is None:
                continue  # déjà comptabilisé dans `unmatched` ci-dessus
            rating = player_ratings[rating_name]
            w = max(float(getattr(sp, "expected_minutes", 0.0) or 0.0), 0.0)
            pairs.append((rating, w))
        if len(pairs) < min_players:
            continue
        total_w = sum(w for _, w in pairs)
        if total_w > 0:
            out[nation] = sum(r * w for r, w in pairs) / total_w
        else:  # aucune minute renseignée -> moyenne simple
            out[nation] = sum(r for r, _ in pairs) / len(pairs)
    return out, unmatched


# ---------------------------------------------------------------------------
# Fetch live (réseau/Chrome) — isolé, patchable, dégradation propre.
# ---------------------------------------------------------------------------

def fetch_player_ratings(leagues=None, versions="latest") -> dict[str, float]:
    """Notes FIFA individuelles via SoFIFA (joueurs des grands championnats).

    Isolé et **patchable** par les tests. SoFIFA étant scrapé/fragile (cf. audit),
    toute erreur remonte à l'appelant (qui désactive le tilt qualité).
    """
    import soccerdata as sd

    attempts = ([{"leagues": leagues, "versions": versions}] if leagues is not None
                else [{"versions": versions}, {}])
    last_err: Exception | None = None
    for kwargs in attempts:
        try:
            df = sd.SoFIFA(**kwargs).read_player_ratings()
            return player_ratings_to_dict(df)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"SoFIFA indisponible (scraping cassé en amont ?) : {last_err}")


def reconstruct_team_quality(squads: dict, leagues=None, versions="latest"
                             ) -> dict[str, float]:
    """Note de qualité par sélection, reconstruite depuis les notes joueur SoFIFA."""
    ratings = fetch_player_ratings(leagues=leagues, versions=versions)
    quality, _unmatched = aggregate_squad_quality(squads, ratings)
    return quality


def centered_quality(squads: dict, leagues=None, versions="latest") -> dict[str, float]:
    """Qualité d'effectif reconstruite PUIS centrée/standardisée, prête pour le couplage.

    `squads` est requis : sans effectifs, on ne peut pas reconstruire (et on ne
    fabrique pas) -> renvoie {} (tilt qualité neutralisé).
    """
    if not squads:
        return {}
    return center_quality(reconstruct_team_quality(squads, leagues=leagues,
                                                   versions=versions))
