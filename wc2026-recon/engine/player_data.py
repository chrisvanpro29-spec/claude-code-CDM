"""Alimentation FBref de la couche joueur : composantes par 90 min, aplaties/ajustées.

On BRANCHE une source ; on ne réécrit pas la logique testée. Ce module transforme
les tables saison FBref (`soccerdata.FBref.read_player_season_stats`, colonnes
MultiIndex) en lignes prêtes pour `PlayerMatchStore` : noms de composantes exacts
attendus par `config.COMPONENT_WEIGHTS`, totaux bruts + minutes + compétition, que
`player_form` ramène ensuite par 90 min, pondère par la force de ligue, standardise
(z-score) et agrège — inchangé.

Honnêteté (brief §1) : FBref n'a pas de xG concédé fiable par joueur -> `xg_against`
reste absent (le normalizer le traite comme manquant), jamais fabriqué. La défense
repose sur tacles / interceptions / dégagements / duels.

Cadrage v1 : agrégats de saison. Un agrégat « saison à ce jour » est sans fuite
pour prédire des matchs À VENIR (il ne contient que du passé) ; il n'est PAS
pristine pour rejouer des matchs déjà joués. -> couche joueur pour le live.

Prérequis fetch : Google Chrome installé (navigateur automatisé via soccerdata).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from . import league_strength

# FBref (col aplatie) -> nom de composante canonique (config.COMPONENT_WEIGHTS).
# Valeurs = TOTAUX de saison (player_form fait le /90 et la pondération ligue).
FBREF_COMPONENT_MAP = {
    # attaque
    "Gls": "goals",
    "xG": "xg",
    "Ast": "assists",
    "xAG": "xa",
    "KP": "key_passes",
    "SCA": "chances_created",
    # milieu (KP partagé avec l'attaque)
    "PrgP": "prog_passes",
    "Recov": "recoveries",
    "Cmp%": "pass_pct_pressure",   # NB : % de passes réussies (saison), pas strictement « sous pression »
    # défense
    "Tkl": "tackles",
    "Int": "interceptions",
    "Won": "duels_won",            # duels aériens gagnés (Aerial Duels -> Won)
    "Clr": "clearances",
    # xg_against : volontairement absent (pas de xG concédé fiable par joueur)
}

NINETIES_COL = "90s"

# stat_types FBref à tirer et les colonnes qu'on en garde.
STAT_TYPES = {
    "standard": ["Gls", "xG", "Ast", "xAG", NINETIES_COL],
    "passing": ["KP", "xA", "PrgP", "Cmp%"],
    "goal_shot_creation": ["SCA"],
    "defense": ["Tkl", "TklW", "Int", "Blocks", "Clr"],
    "possession": ["PrgC"],
    "misc": ["Recov", "Won"],
}


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Aplatit un MultiIndex de colonnes FBref en noms simples (niveau le plus spécifique).

    ('Standard','Gls') -> 'Gls' ; ('Unnamed: 5_level_0','90s') -> '90s'.

    FBref répète des noms entre groupes : un même 'Gls' apparaît en TOTAL
    (groupe 'Performance') ET en taux ('Per 90 Minutes'). Aplatir crée alors des
    libellés dupliqués -> une sélection `df['Gls']` renverrait une Series et tout
    test booléen dessus lèverait « truth value of a Series is ambiguous ». On
    déduplique en gardant la PREMIÈRE occurrence (le total, qui précède le /90
    dans l'ordre des colonnes FBref) ; `player_form` fait ensuite le /90 lui-même.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        return df.loc[:, ~df.columns.duplicated(keep="first")]
    flat = []
    for tup in df.columns:
        parts = [str(x) for x in tup if x is not None and str(x)
                 and not str(x).startswith("Unnamed")]
        flat.append(parts[-1] if parts else str(tup[-1]))
    out = df.copy()
    out.columns = flat
    return out.loc[:, ~out.columns.duplicated(keep="first")]


def per90(total, nineties) -> float:
    """Ramène un total par 90 min. Division par zéro gardée -> 0.0."""
    try:
        n = float(nineties)
    except (TypeError, ValueError):
        return 0.0
    if n <= 0:
        return 0.0
    return float(total) / n


def per90_series(totals: pd.Series, nineties: pd.Series) -> pd.Series:
    """Version vectorisée de `per90` (0.0 là où 90s <= 0)."""
    n = pd.to_numeric(nineties, errors="coerce").fillna(0.0)
    t = pd.to_numeric(totals, errors="coerce").fillna(0.0)
    out = t.where(n > 0, 0.0) / n.where(n > 0, 1.0)
    return out.where(n > 0, 0.0)


def league_adjust(value: float, competition: str | None) -> float:
    """Ajuste une valeur par la force de la ligue (un but en L2 != en UCL)."""
    return float(value) * league_strength.strength(competition)


def _scalar(v):
    """Renvoie une valeur scalaire même si `v` est une Series (libellé dupliqué résiduel)."""
    if isinstance(v, pd.Series):
        v = v.iloc[0] if len(v) else None
    return v


def to_store_rows(merged: pd.DataFrame, competition: str, is_national: bool,
                  date: dt.date, player_col: str = "player") -> list[dict]:
    """Transforme un tableau FBref (aplati, 1 ligne/joueur) en lignes PlayerMatchStore.

    Émet des TOTAUX bruts + minutes (= 90s × 90) + competition + is_national + date.
    `player_form` se charge du /90, de la pondération ligue et du z-score.
    Les joueurs sans minutes (90s manquant/0) sont ignorés (jamais devinés).
    """
    rows = []
    for _, r in merged.iterrows():
        nineties = pd.to_numeric(_scalar(r.get(NINETIES_COL)), errors="coerce")
        if pd.isna(nineties) or nineties <= 0:   # scalaire -> test booléen non ambigu
            continue
        row = {
            "player": _scalar(r.get(player_col)),
            "date": date,
            "competition": competition,
            "is_national": is_national,
            "minutes": float(nineties) * 90.0,
        }
        for fbref_col, canon in FBREF_COMPONENT_MAP.items():
            if fbref_col in merged.columns:
                v = pd.to_numeric(_scalar(r.get(fbref_col)), errors="coerce")
                row[canon] = float(v) if not pd.isna(v) else 0.0
        rows.append(row)
    return rows


def components_per90_adjusted(rows: list[dict]) -> list[dict]:
    """Vue d'inspection : composantes par 90 min ajustées ligue, par joueur.

    Pour affichage / predictions live ; le modèle, lui, passe par player_form.
    """
    out = []
    for r in rows:
        nineties = r["minutes"] / 90.0
        view = {"player": r["player"], "competition": r["competition"],
                "is_national": r["is_national"], "nineties": round(nineties, 2)}
        for canon in FBREF_COMPONENT_MAP.values():
            if canon in r:
                view[canon] = round(league_adjust(per90(r[canon], nineties),
                                                  r["competition"]), 4)
        out.append(view)
    return out


# ---------------------------------------------------------------------------
# Fetch live FBref (réseau + Chrome) — isolé, dégradation propre si indisponible.
# ---------------------------------------------------------------------------

def fetch_player_season_components(leagues, seasons, competition_label: str,
                                   is_national: bool, date: dt.date | None = None
                                   ) -> list[dict]:
    """Lit les stat_types FBref, aplatit, fusionne par joueur -> lignes store.

    Lève/retourne proprement : toute erreur réseau/Chrome est laissée remonter à
    l'appelant (qui logge et désactive la couche). Aucune donnée fabriquée.
    """
    import soccerdata as sd

    date = date or dt.date.today()
    fb = sd.FBref(leagues=leagues, seasons=seasons)
    merged: pd.DataFrame | None = None
    for stat_type in STAT_TYPES:
        try:
            raw = fb.read_player_season_stats(stat_type=stat_type)
        except Exception:  # noqa: BLE001 — un stat_type indispo ne tue pas le reste
            continue
        flat = flatten_columns(raw.reset_index())
        keep = ["player"] + [c for c in STAT_TYPES[stat_type] if c in flat.columns]
        keep = list(dict.fromkeys(keep))
        sub = flat[[c for c in keep if c in flat.columns]]
        # Dédoublonne d'éventuels joueurs multi-clubs (somme des totaux).
        if "player" in sub.columns:
            num = sub.drop(columns=["player"]).apply(pd.to_numeric, errors="coerce")
            sub = pd.concat([sub["player"], num], axis=1).groupby("player", as_index=False).sum()
        merged = sub if merged is None else merged.merge(sub, on="player", how="outer")
    if merged is None or merged.empty:
        return []
    return to_store_rows(merged, competition_label, is_national, date)
