"""Tests de l'ingestion des effectifs CDM 2026 (Wikipédia).

Le fixture HTML reproduit la structure RÉELLE de la page (div.mw-heading3 > h3,
paragraphe « Coach: … », puis table.wikitable avec les colonnes
No./Pos./Player/Date of birth/Caps/Goals/Club, joueur en <th> avec un lien dont
le TEXTE est le nom propre — le capitanat est un suffixe HORS-lien, exactement
comme observé sur la page réelle en juin 2026), avec les 26 joueurs réels de la
France et de l'Allemagne (dont accents et capitanat) pour un test réaliste.
"""

from __future__ import annotations

import json

import pytest

from engine import squads as sq

# Données réelles (juin 2026) : (nom, position Wikipédia, est_capitaine, club).
FRANCE_PLAYERS = [
    ("Brice Samba", "GK", False, "Rennes"),
    ("Malo Gusto", "DF", False, "Chelsea"),
    ("Lucas Digne", "DF", False, "Aston Villa"),
    ("Dayot Upamecano", "DF", False, "Bayern Munich"),
    ("Jules Koundé", "DF", False, "Barcelona"),
    ("Manu Koné", "MF", False, "Roma"),
    ("Ousmane Dembélé", "FW", False, "Paris Saint-Germain"),
    ("Aurélien Tchouaméni", "MF", False, "Real Madrid"),
    ("Marcus Thuram", "FW", False, "Inter Milan"),
    ("Kylian Mbappé", "FW", True, "Real Madrid"),
    ("Michael Olise", "FW", False, "Bayern Munich"),
    ("Bradley Barcola", "FW", False, "Paris Saint-Germain"),
    ("N'Golo Kanté", "MF", False, "Fenerbahçe"),
    ("Adrien Rabiot", "MF", False, "Milan"),
    ("Ibrahima Konaté", "DF", False, "Liverpool"),
    ("Mike Maignan", "GK", False, "Milan"),
    ("William Saliba", "DF", False, "Arsenal"),
    ("Warren Zaïre-Emery", "MF", False, "Paris Saint-Germain"),
    ("Théo Hernandez", "DF", False, "Al-Hilal"),
    ("Désiré Doué", "FW", False, "Paris Saint-Germain"),
    ("Lucas Hernandez", "DF", False, "Paris Saint-Germain"),
    ("Jean-Philippe Mateta", "FW", False, "Crystal Palace"),
    ("Robin Risser", "GK", False, "Lens"),
    ("Rayan Cherki", "MF", False, "Manchester City"),
    ("Maghnes Akliouche", "MF", False, "Monaco"),
    ("Maxence Lacroix", "DF", False, "Crystal Palace"),
]

GERMANY_PLAYERS = [
    ("Manuel Neuer", "GK", False, "Bayern Munich"),
    ("Antonio Rüdiger", "DF", False, "Real Madrid"),
    ("Waldemar Anton", "DF", False, "Borussia Dortmund"),
    ("Jonathan Tah", "DF", False, "Bayern Munich"),
    ("Aleksandar Pavlović", "MF", False, "Bayern Munich"),
    ("Joshua Kimmich", "DF", True, "Bayern Munich"),
    ("Kai Havertz", "FW", False, "Arsenal"),
    ("Leon Goretzka", "MF", False, "Bayern Munich"),
    ("Jamie Leweling", "MF", False, "VfB Stuttgart"),
    ("Jamal Musiala", "MF", False, "Bayern Munich"),
    ("Nick Woltemade", "FW", False, "Newcastle United"),
    ("Oliver Baumann", "GK", False, "TSG Hoffenheim"),
    ("Pascal Groß", "MF", False, "Brighton & Hove Albion"),
    ("Maximilian Beier", "FW", False, "Borussia Dortmund"),
    ("Nico Schlotterbeck", "DF", False, "Borussia Dortmund"),
    ("Angelo Stiller", "MF", False, "VfB Stuttgart"),
    ("Florian Wirtz", "MF", False, "Liverpool"),
    ("Nathaniel Brown", "DF", False, "Eintracht Frankfurt"),
    ("Leroy Sané", "MF", False, "Galatasaray"),
    ("Nadiem Amiri", "MF", False, "Mainz 05"),
    ("Alexander Nübel", "GK", False, "VfB Stuttgart"),
    ("David Raum", "DF", False, "RB Leipzig"),
    ("Felix Nmecha", "MF", False, "Borussia Dortmund"),
    ("Malick Thiaw", "DF", False, "Newcastle United"),
    ("Assan Ouédraogo", "MF", False, "RB Leipzig"),
    ("Deniz Undav", "FW", False, "VfB Stuttgart"),
]


def _row_html(i: int, name: str, pos: str, is_captain: bool, club: str) -> str:
    cap = ' <small><i>(<a href="/wiki/Captain_(association_football)" ' \
          'title="Captain (association football)">captain</a>)</i></small>' if is_captain else ""
    slug = name.replace(" ", "_")
    return f"""<tr>
<td>{i}</td><td data-sort-value="{i}">{i}{pos}</td>
<th data-sort-value="{name}" scope="row"><a href="/wiki/{slug}" title="{name} (footballer)">{name}</a>{cap}
</th>
<td>(2000-01-01) January 1, 2000 (aged 26)</td><td>10</td><td>1</td><td>{club}</td>
</tr>"""


def _team_section_html(team: str, players: list[tuple]) -> str:
    rows = "\n".join(_row_html(i + 1, n, p, c, cl) for i, (n, p, c, cl) in enumerate(players))
    return f"""
<div class="mw-heading mw-heading3"><h3 id="{team.replace(' ', '_')}">{team}</h3></div>
<p>Coach: <a href="/wiki/Coach">Some Coach</a></p>
<table class="sortable wikitable plainrowheaders" style="font-size:100%">
<tr><th>No.</th><th>Pos.</th><th>Player</th><th>Date of birth (age)</th><th>Caps</th><th>Goals</th><th>Club</th></tr>
{rows}
</table>
"""


FIXTURE_HTML = "<html><body>" + \
    _team_section_html("France", FRANCE_PLAYERS) + \
    _team_section_html("Germany", GERMANY_PLAYERS) + \
    "</body></html>"


# --- Parsing ---------------------------------------------------------------

def test_parses_two_realistic_squads_with_expected_counts():
    result = sq.parse_squads_page(FIXTURE_HTML, teams=["France", "Germany"])
    assert set(result) == {"France", "Germany"}
    assert len(result["France"]) == 26   # ~26 joueurs/équipe (brief)
    assert len(result["Germany"]) == 26


def test_parsed_names_match_real_players_and_strip_captain_suffix():
    result = sq.parse_squads_page(FIXTURE_HTML, teams=["France", "Germany"])
    assert "Kylian Mbappé" in result["France"]          # capitaine : suffixe retiré
    assert "Jules Koundé" in result["France"]           # accents préservés dans le nom
    assert not any("captain" in n.lower() for n in result["France"])
    assert "Joshua Kimmich" in result["Germany"]
    assert result["France"][0] == "Brice Samba"         # ordre du tableau conservé


def test_team_not_on_page_is_absent_never_guessed():
    result = sq.parse_squads_page(FIXTURE_HTML, teams=["France", "Brazil"])
    assert "France" in result
    assert "Brazil" not in result                        # absent, pas deviné/fabriqué


def test_alias_resolution_finds_heading_under_known_alias(monkeypatch):
    # Un heading Wikipédia "USA" doit être retrouvé pour la cible canonique
    # "United States" via la table d'alias partagée avec config.TEAM_NAME_MAP.
    monkeypatch.setitem(sq.NAME_ALIASES, "USA", "United States")
    html = "<html><body>" + _team_section_html(
        "USA", [("Christian Pulisic", "FW", False, "Milan")] * 6) + "</body></html>"
    result = sq.parse_squads_page(html, teams=["United States"])
    assert "United States" in result
    assert len(result["United States"]) == 6


# --- normalize_name / reconcile_names ---------------------------------------

def test_normalize_name_strips_accents_case_punctuation():
    assert sq.normalize_name("Jules Koundé") == "jules kounde"
    assert sq.normalize_name("N'Golo Kanté") == "ngolo kante"
    assert sq.normalize_name("  Désiré   Doué ") == "desire doue"


def test_reconcile_names_exact_after_normalization():
    matched, unmatched = sq.reconcile_names(["Jules Koundé"], ["Jules Kounde"])
    assert matched == {"Jules Koundé": "Jules Kounde"}
    assert unmatched == []


def test_reconcile_names_fuzzy_above_threshold():
    # légère variante orthographique -> match approché accepté (similarité élevée)
    matched, unmatched = sq.reconcile_names(["Ousmane Dembele"], ["Ousmane Dembélé"],
                                            threshold=0.85)
    assert matched.get("Ousmane Dembele") == "Ousmane Dembélé"
    assert unmatched == []


def test_reconcile_names_never_guesses_below_threshold():
    matched, unmatched = sq.reconcile_names(["Totally Unknown Player"],
                                            ["Jules Koundé", "Kylian Mbappé"])
    assert "Totally Unknown Player" not in matched
    assert unmatched == ["Totally Unknown Player"]


# --- Conversion SquadPlayer + persistance -----------------------------------

def test_to_squad_players_uses_neutral_default_weights():
    squads = {"France": ["Kylian Mbappé", "Jules Koundé"]}
    out = sq.to_squad_players(squads)
    assert len(out["France"]) == 2
    sp = out["France"][0]
    assert sp.player == "Kylian Mbappé"
    assert sp.position == sq.DEFAULT_POSITION
    assert sp.expected_minutes == sq.DEFAULT_EXPECTED_MINUTES


def test_write_and_load_squads_json_roundtrip(tmp_path):
    path = tmp_path / "squads.json"
    squads = {"France": ["Kylian Mbappé"], "Germany": ["Joshua Kimmich"]}
    sq.write_squads_json(squads, path=path)
    assert json.loads(path.read_text(encoding="utf-8")) == squads
    assert sq.load_squads_json(path=path) == squads


def test_load_squad_players_end_to_end(tmp_path):
    path = tmp_path / "squads.json"
    sq.write_squads_json({"France": ["Kylian Mbappé"]}, path=path)
    out = sq.load_squad_players(path=path)
    assert out["France"][0].player == "Kylian Mbappé"


# --- Ingestion ponctuelle : idempotente par défaut, --refresh re-tire -------

def test_ingest_reuses_cache_without_refresh(tmp_path, monkeypatch):
    path = tmp_path / "squads.json"
    calls = {"fetch": 0}

    def fake_fetch():
        calls["fetch"] += 1
        return FIXTURE_HTML

    monkeypatch.setattr(sq, "fetch_squads_html", fake_fetch)
    monkeypatch.setattr(sq, "canonical_teams", lambda: ["France", "Germany"])

    first = sq.ingest(refresh=False, path=path)
    assert calls["fetch"] == 1 and len(first["France"]) == 26

    second = sq.ingest(refresh=False, path=path)     # cache déjà présent
    assert calls["fetch"] == 1                        # pas de second fetch
    assert second == first


def test_ingest_refresh_forces_refetch(tmp_path, monkeypatch):
    path = tmp_path / "squads.json"
    calls = {"fetch": 0}

    def fake_fetch():
        calls["fetch"] += 1
        return FIXTURE_HTML

    monkeypatch.setattr(sq, "fetch_squads_html", fake_fetch)
    monkeypatch.setattr(sq, "canonical_teams", lambda: ["France", "Germany"])

    sq.ingest(refresh=False, path=path)
    sq.ingest(refresh=True, path=path)                 # remplacement blessure -> re-tire
    assert calls["fetch"] == 2
