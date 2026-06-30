"""Qualité d'effectif (SoFIFA) — 4e tilt centré (brief §2).

`SoFIFA.read_team_ratings` donne une note d'effectif par sélection. On la **centre**
(et standardise) sur la population des sélections : c'est l'écart à la normale qui
compte, jamais l'absolu — la qualité de fond est déjà dans α/β du modèle de base
(anti-double-comptage). Sortie : un scalaire centré/borné par sélection, branché
comme tilt via `coupling.adjusted_lambdas(qual_home=…, qual_away=…)`.

Alternative documentée (non implémentée v1) : valeur marché Transfermarkt via
scraper dédié (fragile + ToS), même traitement centré, si explicitement souhaitée.
"""

from __future__ import annotations

import statistics


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
# Cible : SÉLECTIONS NATIONALES (pas les clubs).
# ---------------------------------------------------------------------------
# Par défaut, SoFIFA ne connaît que les 5 grands championnats de CLUBS -> sans
# ciblage, read_team_ratings renvoie Manchester City, Real Madrid… Les sélections
# nationales sont une « ligue » à part sur SoFIFA (id 78, « Friendly International »,
# nationName « International »). On l'enregistre dans le league_dict de soccerdata
# et on la cible explicitement. (Si SoFIFA renommait cette ligue, ajuster la valeur.)
SOFIFA_NATIONAL_LEAGUE_KEY = "INT-National Teams"
SOFIFA_NATIONAL_LEAGUE_VALUE = "[International] Friendly International"

# Indices de clubs connus -> sert au test de non-régression « pas des clubs ».
KNOWN_CLUB_LEAGUE_KEYS = {"ENG-Premier League", "ESP-La Liga", "ITA-Serie A",
                          "GER-Bundesliga", "FRA-Ligue 1"}


def _register_national_league() -> None:
    """Enregistre la ligue des sélections nationales dans le league_dict de soccerdata.

    Mutation en place du dict partagé -> visible par SoFIFA (qui exige que la clé
    de ligue existe dans LEAGUE_DICT avant de la sélectionner).
    """
    from soccerdata import _config as sdcfg
    sdcfg.LEAGUE_DICT.setdefault(
        SOFIFA_NATIONAL_LEAGUE_KEY, {"SoFIFA": SOFIFA_NATIONAL_LEAGUE_VALUE})


def _team_ratings_to_dict(df, ratings_col: str | None = None) -> dict[str, float]:
    """Parser pur (sans réseau) : DataFrame SoFIFA -> {nom_équipe: note_overall}."""
    col = ratings_col
    if col is None:
        for cand in ("overall", "Overall", "OVR", "ovr"):
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


def _sofifa_team_ratings(leagues, versions="latest"):
    """Construit SoFIFA ciblé sur `leagues` et renvoie read_team_ratings().

    Isolé (réseau/Chrome) et **patchable** par les tests. SoFIFA étant scrapé et
    fragile (cf. audit), on tente quelques signatures de constructeur.
    """
    import soccerdata as sd

    _register_national_league()
    last_err: Exception | None = None
    for kwargs in ({"leagues": leagues, "versions": versions},
                   {"leagues": leagues}):
        try:
            return sd.SoFIFA(**kwargs).read_team_ratings()
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"SoFIFA indisponible (scraping cassé en amont ?) : {last_err}")


def fetch_team_quality(leagues=None, versions="latest") -> dict[str, float]:
    """Notes d'effectif des SÉLECTIONS NATIONALES SoFIFA. Dégradation propre.

    Retourne {sélection: note_overall} (France, Germany, …). Cible la ligue des
    sélections nationales par défaut ; toute erreur réseau remonte à l'appelant
    (qui désactive le tilt qualité). Aucune note fabriquée.
    """
    leagues = leagues if leagues is not None else [SOFIFA_NATIONAL_LEAGUE_KEY]
    df = _sofifa_team_ratings(leagues, versions=versions)
    return _team_ratings_to_dict(df)


def centered_quality(leagues=None, versions="latest") -> dict[str, float]:
    """Notes d'effectif des sélections nationales, centrées/standardisées."""
    return center_quality(fetch_team_quality(leagues=leagues, versions=versions))
