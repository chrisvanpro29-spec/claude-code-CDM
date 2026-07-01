"""Ingestion des effectifs CDM 2026 — Wikipédia « 2026 FIFA World Cup squads ».

Parse les tables par sélection en `{nation: [noms de joueurs]}`, aligne les noms
de nations sur `results.csv` (source A) et écrit `data/squads.json`.

Les effectifs sont figés (annoncés le 2 juin) : ingestion PONCTUELLE, pas un flux
récurrent (contrairement au collecteur de cotes). `ingest(refresh=True)` re-tire
en cas de remplacement sur blessure.

Recalage des noms joueur (Wikipédia ↔ SoFIFA ↔ FBref) : `normalize_name` (sans
accents, minuscules) + `reconcile_names` (exact puis approché, seuil élevé) — les
non-appariés sont renvoyés pour être loggés, jamais devinés.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import unicodedata
from pathlib import Path

import requests

import config
from audit.paths import DATA_DIR
from engine.player_form import SquadPlayer

WIKI_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
TIMEOUT = 30
SQUADS_JSON = DATA_DIR / "squads.json"

# Nb de joueurs attendu par effectif (ordre de grandeur, pas une contrainte dure :
# une sélection peut varier en cas de remplacement blessure de dernière minute).
EXPECTED_SQUAD_SIZE = 26

# Alias nom Wikipédia -> nom canonique results.csv. On réutilise la table de
# config (déjà éprouvée par le collecteur de cotes) : direction identique
# (nom source externe -> nom canonique).
NAME_ALIASES: dict[str, str] = dict(config.TEAM_NAME_MAP)

# Poids neutre : une liste d'effectif Wikipédia n'est PAS une composition
# probable. Faute de onze titulaire réel, tous les joueurs reçoivent le même
# poids -> pas de note de forme fabriquée sur une supposée titularisation.
DEFAULT_POSITION = "UNK"
DEFAULT_EXPECTED_MINUTES = 90.0


# ---------------------------------------------------------------------------
# Fetch (réseau) — isolé, patchable par les tests.
# ---------------------------------------------------------------------------

def fetch_squads_html() -> str:
    """Télécharge la page Wikipédia des effectifs CDM 2026."""
    resp = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (wc2026-recon)"},
                        timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Parsing (pur, testable sans réseau)
# ---------------------------------------------------------------------------

def _find_heading(soup, name: str):
    """Heading <h2>/<h3> dont le texte correspond exactement à `name`."""
    return soup.find(lambda t: t.name in ("h2", "h3") and t.get_text(strip=True) == name)


def _find_squad_table(soup, heading_text: str):
    """Table wikitable qui suit un heading donné (structure Wikipédia : le
    heading est enveloppé dans un `div.mw-heading`, suivi d'un paragraphe
    'Coach: …' puis de la table de l'effectif)."""
    h = _find_heading(soup, heading_text)
    if h is None:
        return None
    node = h.parent  # div.mw-heading{2,3}
    for _ in range(10):
        node = node.find_next_sibling()
        if node is None:
            break
        if node.name == "table" and "wikitable" in (node.get("class") or []):
            return node
        if node.name == "div" and "mw-heading" in (node.get("class") or []):
            break  # section suivante atteinte sans trouver de table
    return None


def _player_name_from_cell(cell) -> str | None:
    """Nom du joueur depuis la cellule 'Player'. Priorité au texte du 1er lien
    (exclut les suffixes hors-lien comme « (captain) » ajoutés en <small><i>)."""
    a = cell.find("a")
    if a is not None:
        text = a.get_text(strip=True)
        return text or None
    text = cell.get_text(" ", strip=True)
    return text or None


def parse_squads_page(html: str, teams: list[str] | None = None) -> dict[str, list[str]]:
    """Parse la page (ou un extrait) -> `{nation: [noms de joueurs]}`.

    `teams` : liste des noms canoniques (results.csv) à rechercher. Par défaut,
    les 48 sélections de la CDM 2026 (dérivées de la source A). Une sélection
    dont le heading est introuvable (même après alias) est absente du résultat
    — jamais devinée ; l'appelant peut logger les manquants par différence.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    teams = teams if teams is not None else canonical_teams()

    # Index inverse : nom canonique -> nom Wikipédia probable à chercher.
    # 1) le nom canonique lui-même ; 2) tout alias connu qui POINTE vers lui.
    aliases_for = {t: [t] + [src for src, dst in NAME_ALIASES.items() if dst == t]
                  for t in teams}

    out: dict[str, list[str]] = {}
    for canon in teams:
        table = None
        for candidate in aliases_for[canon]:
            table = _find_squad_table(soup, candidate)
            if table is not None:
                break
        if table is None:
            continue
        names = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 3:
                continue
            name = _player_name_from_cell(cells[2])
            if name:
                names.append(name)
        if names:
            out[canon] = names
    return out


# ---------------------------------------------------------------------------
# Alignement sur results.csv
# ---------------------------------------------------------------------------

def canonical_teams() -> list[str]:
    """Les 48 sélections de la CDM 2026, telles qu'elles apparaissent dans results.csv."""
    from . import data
    wc = data.wc2026_matches()
    return sorted(set(wc["home_team"]) | set(wc["away_team"]))


# ---------------------------------------------------------------------------
# Recalage des noms joueur (Wikipédia ↔ SoFIFA ↔ FBref)
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Sans accents, minuscules, ponctuation retirée, espaces normalisés.

    'N'Golo Kanté' -> 'ngolo kante' (apostrophe retirée sans espace, comme dans
    les graphies alternatives courantes) ; 'Jules Koundé' -> 'jules kounde' ;
    'Zaïre-Emery' -> 'zaire emery' (tiret -> espace : nom composé).
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = stripped.replace("'", "").replace("’", "")  # apostrophes : retirées, pas d'espace
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", stripped).lower()
    return re.sub(r"\s+", " ", cleaned).strip()


def reconcile_names(names: list[str], candidates, threshold: float = 0.90
                    ) -> tuple[dict[str, str], list[str]]:
    """Recale chaque nom de `names` sur le meilleur nom de `candidates`.

    Étapes : (1) correspondance exacte après normalisation ; (2) correspondance
    approchée (similarité >= `threshold`) ; sinon non-apparié. **Ne devine
    jamais** : sous le seuil, le nom est renvoyé dans `unmatched`, jamais forcé.

    Retourne (matched: {nom_original: nom_candidat}, unmatched: [nom_original]).
    """
    candidates = list(candidates)
    norm_to_candidate: dict[str, str] = {}
    for c in candidates:
        norm_to_candidate.setdefault(normalize_name(c), c)

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    norm_keys = list(norm_to_candidate.keys())
    for name in names:
        n = normalize_name(name)
        if n in norm_to_candidate:
            matched[name] = norm_to_candidate[n]
            continue
        best_key, best_ratio = None, 0.0
        for key in norm_keys:
            ratio = difflib.SequenceMatcher(None, n, key).ratio()
            if ratio > best_ratio:
                best_key, best_ratio = key, ratio
        if best_key is not None and best_ratio >= threshold:
            matched[name] = norm_to_candidate[best_key]
        else:
            unmatched.append(name)
    return matched, unmatched


# ---------------------------------------------------------------------------
# Persistance + conversion SquadPlayer
# ---------------------------------------------------------------------------

def write_squads_json(squads: dict[str, list[str]], path: Path | None = None) -> Path:
    path = path or SQUADS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(squads, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_squads_json(path: Path | None = None) -> dict[str, list[str]]:
    path = path or SQUADS_JSON
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def to_squad_players(squads: dict[str, list[str]],
                     default_position: str = DEFAULT_POSITION,
                     default_minutes: float = DEFAULT_EXPECTED_MINUTES
                     ) -> dict[str, list[SquadPlayer]]:
    """Convertit `{nation: [nom, ...]}` -> `{nation: [SquadPlayer, ...]}`.

    Poids neutre et uniforme (cf. module docstring) : une liste d'effectif
    n'est pas une composition probable, on ne fabrique pas de titulaires.
    """
    return {
        nation: [SquadPlayer(player=name, position=default_position,
                             expected_minutes=default_minutes) for name in names]
        for nation, names in squads.items()
    }


def load_squad_players(path: Path | None = None) -> dict[str, list[SquadPlayer]]:
    """Lit `data/squads.json` et renvoie directement la forme SquadPlayer
    attendue par `squad_quality.centered_quality` et `player_form.team_notes`."""
    return to_squad_players(load_squads_json(path))


# ---------------------------------------------------------------------------
# Orchestration — ingestion ponctuelle
# ---------------------------------------------------------------------------

def ingest(teams: list[str] | None = None, refresh: bool = False,
          path: Path | None = None) -> dict[str, list[str]]:
    """Ingestion ponctuelle des effectifs. `refresh=True` re-tire (remplacement
    blessure) ; sinon réutilise `data/squads.json` s'il existe déjà (idempotent).
    """
    path = path or SQUADS_JSON
    if path.exists() and not refresh:
        return load_squads_json(path)

    html = fetch_squads_html()
    teams = teams if teams is not None else canonical_teams()
    squads = parse_squads_page(html, teams=teams)
    write_squads_json(squads, path=path)
    return squads
