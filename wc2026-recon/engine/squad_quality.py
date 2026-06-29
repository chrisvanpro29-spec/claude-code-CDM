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


def fetch_team_quality(seasons=None) -> dict[str, float]:
    """Lit les notes d'effectif SoFIFA par équipe (réseau). Dégradation propre.

    Retourne {equipe: note_overall}. Toute erreur réseau est laissée remonter à
    l'appelant (qui logge et désactive le tilt qualité). Aucune note fabriquée.
    """
    import soccerdata as sd

    # SoFIFA est scrapé et fragile (cf. audit) : on tente plusieurs signatures de
    # constructeur selon la version de soccerdata, et on laisse remonter l'erreur
    # si le site a changé (l'appelant désactivera proprement le tilt qualité).
    sofifa = None
    attempts = ([{"seasons": seasons}] if seasons is not None
                else [{"versions": "latest"}, {}])
    last_err: Exception | None = None
    for kwargs in attempts:
        try:
            sofifa = sd.SoFIFA(**kwargs)
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    if sofifa is None:
        raise RuntimeError(f"SoFIFA indisponible (scraping cassé en amont ?) : {last_err}")
    df = sofifa.read_team_ratings()

    # Colonne de note globale : 'overall' si présente, sinon 1re colonne numérique.
    col = None
    for cand in ("overall", "Overall", "OVR", "ovr"):
        if cand in df.columns:
            col = cand
            break
    if col is None:
        numeric = df.select_dtypes("number")
        if numeric.empty:
            return {}
        col = numeric.columns[0]

    # Index : nom d'équipe (peut être MultiIndex league/team).
    names = (df.index.get_level_values(-1) if hasattr(df.index, "get_level_values")
             else df.index)
    out: dict[str, float] = {}
    for name, val in zip(names, df[col].tolist()):
        try:
            out[str(name)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def centered_quality(seasons=None) -> dict[str, float]:
    """Notes d'effectif SoFIFA centrées/standardisées, prêtes pour le couplage."""
    return center_quality(fetch_team_quality(seasons=seasons))
