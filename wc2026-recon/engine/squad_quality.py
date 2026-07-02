"""Qualité d'effectif — 4e tilt centré, dérivée de FBref UNIQUEMENT.

SoFIFA est abandonné : scraping confirmé cassé (la page d'accueil ne renvoie
plus la structure attendue, testé deux fois après correction de la résolution
de versions). La note de qualité est désormais **reconstruite depuis les
composantes FBref** déjà calculées par `player_data.components_per90_adjusted`
(buts, xG, passes clés, tacles… par 90 min, ajustées force de ligue) :

  1. pour chaque joueur de l'effectif (Wikipédia, `squads.load_squads_json`),
     une note scalaire = somme pondérée de ses composantes
     (poids = `config.COMPONENT_WEIGHTS`, mêmes pondérations que la forme) ;
  2. note d'équipe = moyenne pondérée par les minutes attendues des joueurs
     retrouvés dans FBref (recalage de noms Wikipédia↔FBref uniquement,
     via `squads.reconcile_names` — jamais deviné) ;
  3. centrage (z-score) sur la moyenne des sélections couvertes, comme avant :
     c'est l'écart à la normale qui compte, jamais l'absolu (la qualité de
     fond est déjà dans α/β du modèle de base — anti-double-comptage).

Couverture insuffisante (trop peu de joueurs d'une sélection retrouvés dans
FBref) -> sélection OMISE, repli force équipe seule. Aucune note fabriquée.

Limite assumée : FBref couvre surtout les grands championnats -> riche pour
les favoris, pauvre pour les petites nations (repli).
"""

from __future__ import annotations

import statistics
import time

import config

# Nb minimal de joueurs d'un effectif retrouvés dans FBref pour oser une note.
MIN_PLAYERS_FOR_QUALITY = 6

# Championnats de clubs interrogés pour construire le vivier de composantes
# joueur, avec le libellé de compétition attendu par league_strength.
QUALITY_LEAGUES = {
    "ENG-Premier League": "Premier League",
    "ESP-La Liga": "La Liga",
    "ITA-Serie A": "Serie A",
    "GER-Bundesliga": "Bundesliga",
    "FRA-Ligue 1": "Ligue 1",
}
QUALITY_SEASONS = "2526"   # saison de club la plus récente avant le tournoi


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
# Note joueur depuis les composantes FBref (pur, testable sans réseau)
# ---------------------------------------------------------------------------

def player_quality_score(components: dict) -> float:
    """Note scalaire d'un joueur = somme pondérée de ses composantes par 90.

    `components` : une entrée de `player_data.components_per90_adjusted`
    (valeurs déjà par 90 min et ajustées force de ligue). Les poids sont ceux
    de `config.COMPONENT_WEIGHTS` (buts/xG plus lourds que passes brutes) ;
    `xg_against` (absent de FBref, jamais fabriqué) serait compté négatif.
    """
    score = 0.0
    for comp, weight in config.COMPONENT_WEIGHTS.items():
        val = components.get(comp)
        if val is None:
            continue
        sign = -1.0 if comp == "xg_against" else 1.0
        score += weight * sign * float(val)
    return score


def quality_scores_from_components(view: list[dict]) -> dict[str, float]:
    """{nom_joueur: note scalaire} depuis la sortie de components_per90_adjusted.

    Un joueur présent dans plusieurs lignes (multi-compétitions) est agrégé par
    moyenne pondérée par ses 90s (le contexte où il a le plus joué pèse plus).
    """
    acc: dict[str, list[tuple[float, float]]] = {}
    for row in view:
        name = row.get("player")
        if not name:
            continue
        weight = max(float(row.get("nineties") or 0.0), 0.0)
        acc.setdefault(str(name), []).append((player_quality_score(row), weight))
    out: dict[str, float] = {}
    for name, pairs in acc.items():
        total_w = sum(w for _, w in pairs)
        if total_w > 0:
            out[name] = sum(s * w for s, w in pairs) / total_w
        else:
            out[name] = sum(s for s, _ in pairs) / len(pairs)
    return out


# ---------------------------------------------------------------------------
# Agrégation par sélection (recalage Wikipédia↔FBref, minutes-pondérée)
# ---------------------------------------------------------------------------

def aggregate_squad_quality(squads: dict, player_scores: dict[str, float],
                            min_players: int = MIN_PLAYERS_FOR_QUALITY
                            ) -> tuple[dict[str, float], list[str]]:
    """Agrège les notes joueur (FBref) par sélection, pondérées par les minutes.

    `squads` : {sélection: [SquadPlayer(player, position, expected_minutes)]}.
    Les noms (Wikipédia) sont recalés sur ceux de `player_scores` (FBref) via
    `squads.reconcile_names` : exact après normalisation, puis approché à seuil
    élevé — jamais deviné. Retourne ({sélection: note}, non_appariés) ; une
    sélection dont trop peu de joueurs sont retrouvés est OMISE (couverture
    insuffisante -> repli force équipe seule). Aucune note fabriquée.
    """
    from .squads import reconcile_names  # import tardif : évite un cycle au chargement

    out: dict[str, float] = {}
    unmatched: list[str] = []
    for nation, squad in squads.items():
        names = [getattr(sp, "player", None) for sp in squad]
        matched, not_found = reconcile_names([n for n in names if n], player_scores)
        unmatched.extend(f"{nation}:{n}" for n in not_found)

        pairs = []  # (note, poids)
        for sp in squad:
            player = getattr(sp, "player", None)
            score_name = matched.get(player)
            if score_name is None:
                continue  # déjà comptabilisé dans `unmatched` ci-dessus
            score = player_scores[score_name]
            w = max(float(getattr(sp, "expected_minutes", 0.0) or 0.0), 0.0)
            pairs.append((score, w))
        if len(pairs) < min_players:
            continue
        total_w = sum(w for _, w in pairs)
        if total_w > 0:
            out[nation] = sum(s * w for s, w in pairs) / total_w
        else:  # aucune minute renseignée -> moyenne simple
            out[nation] = sum(s for s, _ in pairs) / len(pairs)
    return out, unmatched


# ---------------------------------------------------------------------------
# Fetch live FBref (réseau/Chrome) — isolé, patchable, dégradation propre.
# ---------------------------------------------------------------------------

# Anti rate-limit FBref : tirer plusieurs grandes ligues à la suite déclenche
# CAPTCHA / blocage IP ("Could not retrieve page content"). Le problème vient de
# la FRÉQUENCE des requêtes, pas du code métier -> on espace explicitement les
# appels par ligue, et on réessaie avec backoff avant de sauter une ligue.
FBREF_LEAGUE_DELAY_S = 8.0     # pause entre deux ligues (5-10 s recommandé)
FBREF_MAX_RETRIES = 2          # ré-essais par ligue après le 1er échec
FBREF_BACKOFF_BASE_S = 20.0    # attente avant retry, doublée à chaque échec


def _fetch_league_components(player_data, league_key: str, competition_label: str,
                             seasons) -> list[dict]:
    """Une ligue, avec retries + backoff. Renvoie [] si toujours en échec
    (loggé) : l'échec d'une ligue ne bloque jamais les autres."""
    last_err: Exception | None = None
    for attempt in range(1 + FBREF_MAX_RETRIES):
        if attempt > 0:
            wait = FBREF_BACKOFF_BASE_S * (2 ** (attempt - 1))
            print(f"[quality] {league_key} : échec ({type(last_err).__name__}), "
                  f"retry {attempt}/{FBREF_MAX_RETRIES} dans {wait:.0f}s…")
            time.sleep(wait)
        try:
            rows = player_data.fetch_player_season_components(
                leagues=league_key, seasons=seasons,
                competition_label=competition_label, is_national=False)
            if rows:  # [] = tous les stat_types ont échoué -> traité comme un échec
                return player_data.components_per90_adjusted(rows)
            last_err = RuntimeError("aucune ligne renvoyée (stat_types tous en échec)")
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"[quality] {league_key} : abandonné après {1 + FBREF_MAX_RETRIES} "
          f"tentatives ({type(last_err).__name__}: {last_err}) -> ligue sautée.")
    return []


def fetch_player_components(leagues: dict[str, str] | None = None,
                            seasons: str | None = None) -> list[dict]:
    """Composantes par 90 ajustées, tous joueurs des championnats interrogés.

    Isolé et **patchable** par les tests. FBref étant lent/rate-limité (cf.
    audit), les appels par ligue sont espacés de FBREF_LEAGUE_DELAY_S et chaque
    ligue est réessayée avec backoff avant d'être sautée (loggée) — l'échec
    d'une ligue ne bloque jamais les autres. Si TOUTES échouent, on lève une
    erreur claire (l'appelant désactive le tilt qualité).
    """
    from . import player_data

    leagues = leagues if leagues is not None else QUALITY_LEAGUES
    seasons = seasons if seasons is not None else QUALITY_SEASONS
    view: list[dict] = []
    for i, (league_key, competition_label) in enumerate(leagues.items()):
        if i > 0:
            time.sleep(FBREF_LEAGUE_DELAY_S)  # espacement anti-CAPTCHA entre ligues
        view.extend(_fetch_league_components(player_data, league_key,
                                             competition_label, seasons))
    if not view:
        raise RuntimeError(
            f"FBref : aucune composante joueur récupérée sur {len(leagues)} "
            "ligue(s) (rate-limit/CAPTCHA/IP block ? réessayer plus tard)")
    return view


def reconstruct_team_quality(squads: dict, leagues: dict[str, str] | None = None,
                             seasons: str | None = None) -> dict[str, float]:
    """Note de qualité par sélection, reconstruite depuis les composantes FBref."""
    view = fetch_player_components(leagues=leagues, seasons=seasons)
    scores = quality_scores_from_components(view)
    quality, _unmatched = aggregate_squad_quality(squads, scores)
    return quality


def centered_quality(squads: dict, leagues: dict[str, str] | None = None,
                     seasons: str | None = None) -> dict[str, float]:
    """Qualité d'effectif reconstruite (FBref) puis centrée, prête pour le couplage.

    `squads` est requis : sans effectifs, on ne peut pas reconstruire (et on ne
    fabrique pas) -> renvoie {} (tilt qualité neutralisé).
    """
    if not squads:
        return {}
    return center_quality(reconstruct_team_quality(squads, leagues=leagues,
                                                   seasons=seasons))


# ---------------------------------------------------------------------------
# Mode diagnostic — « 0 équipes notées » : (a) stats FBref pas récupérées, ou
# (b) recalage des noms Wikipédia↔FBref en échec ? Aucun changement de
# comportement du chemin de scoring : lecture seule + rapport.
# ---------------------------------------------------------------------------

def diagnose_nation(nation: str = "France", squads: dict | None = None,
                    view: list[dict] | None = None,
                    leagues: dict[str, str] | None = None,
                    seasons: str | None = None) -> dict:
    """Diagnostique la chaîne effectif Wikipédia -> stats FBref pour UNE sélection.

    Retourne (et affiche) : taille du vivier FBref (par compétition), taille de
    l'effectif, joueurs appariés vs non appariés (liste complète des échecs),
    échantillon de noms FBref pour inspection visuelle, et un verdict :
      (a) vivier FBref vide/maigre -> les stats ne sont pas récupérées ;
      (b) vivier fourni mais appariements ~0 -> le recalage de noms échoue.

    `view` peut être injecté (tests / réutilisation d'un tirage déjà fait) ;
    sinon on tire via fetch_player_components (mêmes délais/retries que le
    chemin normal).
    """
    from .squads import reconcile_names

    if squads is None:
        from .squads import load_squad_players
        squads = load_squad_players()

    report: dict = {"nation": nation}
    print(f"[diagnose] sélection ciblée : {nation}")

    # --- Étape 1 : le vivier FBref -------------------------------------------
    fetch_error: str | None = None
    if view is None:
        try:
            view = fetch_player_components(leagues=leagues, seasons=seasons)
        except Exception as e:  # noqa: BLE001
            fetch_error = f"{type(e).__name__}: {e}"
            view = []
    pool_names = sorted({str(r["player"]) for r in view if r.get("player")})
    by_comp: dict[str, int] = {}
    for r in view:
        by_comp[str(r.get("competition"))] = by_comp.get(str(r.get("competition")), 0) + 1
    report.update({"pool_size": len(pool_names), "pool_by_competition": by_comp,
                   "fetch_error": fetch_error})
    print(f"[diagnose] vivier FBref : {len(pool_names)} joueurs distincts, "
          f"par compétition : {by_comp or '∅'}"
          + (f" | erreur fetch : {fetch_error}" if fetch_error else ""))
    if pool_names:
        print(f"[diagnose] échantillon de noms FBref (graphie réelle) : {pool_names[:10]}")

    # --- Étape 2 : le recalage pour la sélection ------------------------------
    squad = squads.get(nation, [])
    squad_names = [getattr(sp, "player", None) for sp in squad]
    squad_names = [n for n in squad_names if n]
    report["squad_size"] = len(squad_names)
    if not squad_names:
        print(f"[diagnose] ⚠️ effectif {nation} vide/introuvable dans squads.json "
              "-> lancer ingest_squads.py d'abord.")
        report["verdict"] = "effectif absent (ni (a) ni (b) : squads.json manquant)"
        return report

    matched, unmatched = reconcile_names(squad_names, pool_names)
    report.update({"n_matched": len(matched), "n_unmatched": len(unmatched),
                   "unmatched": unmatched,
                   "matched_examples": dict(list(matched.items())[:5])})
    print(f"[diagnose] effectif {nation} : {len(squad_names)} joueurs | "
          f"appariés FBref : {len(matched)} | non appariés : {len(unmatched)}")
    if matched:
        print(f"[diagnose] exemples d'appariements réussis : "
              f"{dict(list(matched.items())[:5])}")
    if unmatched:
        print(f"[diagnose] noms NON appariés ({len(unmatched)}) : {unmatched}")

    # --- Verdict ---------------------------------------------------------------
    if not pool_names:
        verdict = ("(a) stats FBref PAS récupérées : vivier vide"
                   + (f" ({fetch_error})" if fetch_error else ""))
    elif len(matched) < MIN_PLAYERS_FOR_QUALITY:
        verdict = (f"(b) recalage de noms en échec : vivier de {len(pool_names)} "
                   f"joueurs mais seulement {len(matched)} apparié(s) "
                   f"(< {MIN_PLAYERS_FOR_QUALITY} requis) -> sélection omise")
    else:
        verdict = (f"OK : {len(matched)} appariés (>= {MIN_PLAYERS_FOR_QUALITY}) — "
                   "la sélection devrait être notée ; si '0 équipes notées' "
                   "persiste, le problème est en aval de l'agrégation")
    report["verdict"] = verdict
    print(f"[diagnose] VERDICT : {verdict}")
    return report


if __name__ == "__main__":
    import sys

    diagnose_nation(sys.argv[1] if len(sys.argv) > 1 else "France")
