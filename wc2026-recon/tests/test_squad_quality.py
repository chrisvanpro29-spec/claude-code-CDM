"""Tests de la qualité d'effectif (dérivée FBref uniquement) et de son couplage.

SoFIFA est abandonné (scraping cassé, confirmé) : la note de qualité est
reconstruite depuis les composantes FBref (`player_data.components_per90_adjusted`),
agrégée par sélection (minutes-pondérée, recalage Wikipédia↔FBref), puis centrée.

Couvre : note joueur depuis composantes, agrégation (minutes, couverture,
non-appariés), centrage/standardisation, bout-en-bout Wikipédia→FBref→note
centrée sur des effectifs fictifs, et le 4e tilt côté coupling.
"""

from __future__ import annotations

import pytest

import config
from engine import squad_quality as sq
from engine import coupling
from engine.player_form import TeamNotes, SquadPlayer

REF = (0.0, 0.0, 0.0)


def _squad(*names_minutes):
    return [SquadPlayer(player=n, position="MID", expected_minutes=m)
            for n, m in names_minutes]


def _components(player, nineties=10.0, **stats):
    """Une entrée façon player_data.components_per90_adjusted (par 90, ajustée)."""
    base = {"player": player, "competition": "Premier League",
            "is_national": False, "nineties": nineties}
    base.update(stats)
    return base


# --- Note joueur depuis les composantes FBref -------------------------------

def test_player_quality_score_weights_components():
    # buts/xG (poids 1.0) pèsent plus que passes clés (poids 0.4) à valeur égale.
    scorer = sq.player_quality_score(_components("A", goals=1.0, xg=1.0))
    passer = sq.player_quality_score(_components("B", key_passes=1.0, chances_created=1.0))
    assert scorer > passer
    expected = config.COMPONENT_WEIGHTS["goals"] * 1.0 + config.COMPONENT_WEIGHTS["xg"] * 1.0
    assert scorer == pytest.approx(expected)


def test_player_quality_score_ignores_missing_components():
    # composante absente (ex. xg_against, jamais fabriqué par FBref) -> ignorée, pas de crash.
    assert sq.player_quality_score(_components("A")) == 0.0


def test_quality_scores_multi_competition_weighted_by_nineties():
    # Un joueur vu dans 2 compétitions : le contexte le plus joué pèse plus.
    view = [_components("A", nineties=9.0, goals=1.0),
            _components("A", nineties=1.0, goals=0.0)]
    scores = sq.quality_scores_from_components(view)
    w_goals = config.COMPONENT_WEIGHTS["goals"]
    assert scores["A"] == pytest.approx(w_goals * 1.0 * 0.9)   # 9/(9+1)


# --- Agrégation par sélection (recalage Wikipédia↔FBref) --------------------

def test_aggregate_minutes_weighted():
    squads = {"France": _squad(("Mbappé", 90), ("Sub", 0))}
    scores = {"Mbappé": 3.0, "Sub": 1.0}
    out, _ = sq.aggregate_squad_quality(squads, scores, min_players=1)
    # titulaire (90 min) domine le remplaçant (0 min) -> 3.0, pas 2.0
    assert out["France"] == pytest.approx(3.0)


def test_aggregate_skips_undercovered_nation():
    squads = {"Tuvalu": _squad(("X", 90))}                 # 1 seul joueur connu
    scores = {"X": 2.0}
    out, _ = sq.aggregate_squad_quality(squads, scores, min_players=6)
    assert "Tuvalu" not in out                              # couverture insuffisante -> omise


def test_aggregate_logs_unmatched_never_guesses():
    squads = {"France": _squad(("Mbappé", 90), ("Inconnu Total", 90))}
    scores = {"Mbappé": 3.0}
    out, unmatched = sq.aggregate_squad_quality(squads, scores, min_players=1)
    assert any("Inconnu Total" in u for u in unmatched)     # loggé, jamais deviné
    assert out["France"] == pytest.approx(3.0)              # calculé sur les appariés seuls


def test_aggregate_reconciles_wikipedia_fbref_accents():
    # Wikipédia : accents ; FBref : graphie sans accents -> recalage exact normalisé.
    squads = {"France": _squad(("Kylian Mbappé", 90), ("Jules Koundé", 90))}
    scores = {"Kylian Mbappe": 2.0, "Jules Kounde": 1.0}
    out, unmatched = sq.aggregate_squad_quality(squads, scores, min_players=2)
    assert unmatched == []
    assert out["France"] == pytest.approx(1.5)


# --- Centrage qualité -------------------------------------------------------

def test_center_mean_is_zero():
    centered = sq.center_quality({"A": 80, "B": 82, "C": 78})  # moyenne = 80 = A
    assert centered["A"] == pytest.approx(0.0)          # A == moyenne
    assert centered["B"] > 0 and centered["C"] < 0      # ordre conservé


def test_center_symmetry_opposite():
    centered = sq.center_quality({"hi": 85, "lo": 75})  # symétriques autour de 80
    assert centered["hi"] == pytest.approx(-centered["lo"])


def test_center_zero_std_no_div_zero():
    centered = sq.center_quality({"A": 80, "B": 80})
    assert centered == {"A": 0.0, "B": 0.0}


def test_center_empty():
    assert sq.center_quality({}) == {}


# --- Bout-en-bout : Wikipédia → FBref → note centrée ------------------------

def test_end_to_end_wikipedia_fbref_centered(monkeypatch):
    """Effectifs fictifs (noms façon Wikipédia, accents) + composantes FBref
    simulées (graphies FBref) -> notes reconstruites, recalées, centrées."""
    squads = {
        # 6 joueurs chacun (= MIN_PLAYERS_FOR_QUALITY), accents côté Wikipédia.
        "France": _squad(*[(f"Attaquant-{i} Doué", 90) for i in range(6)]),
        "Germany": _squad(*[(f"Verteidiger-{i} Groß", 90) for i in range(6)]),
        # Sélection sous-couverte : 1 seul joueur dans FBref -> doit être omise.
        "Tuvalu": _squad(("Seul Joueur", 90), ("Fantôme A", 90), ("Fantôme B", 90),
                        ("Fantôme C", 90), ("Fantôme D", 90), ("Fantôme E", 90)),
    }

    # Vivier FBref simulé : mêmes joueurs, graphies sans accents (recalage requis).
    # France : score joueur = 0.8·1.0 + 0.7·1.0 = 1.5 ;
    # Germany : score joueur = 1.0·0.7 + 0.5·0.7 = 1.05 < 1.5.
    fake_view = (
        [_components(f"Attaquant-{i} Doue", goals=0.8, xg=0.7) for i in range(6)]
        + [_components(f"Verteidiger-{i} Gross", tackles=1.0, interceptions=0.5)
           for i in range(6)]
        + [_components("Seul Joueur", goals=0.5)]
    )
    monkeypatch.setattr(sq, "fetch_player_components", lambda **kw: fake_view)

    centered = sq.centered_quality(squads)

    assert set(centered) == {"France", "Germany"}            # Tuvalu omise (couverture)
    assert centered["France"] > 0 > centered["Germany"]      # 1.5 > moyenne > 1.05
    assert centered["France"] == pytest.approx(-centered["Germany"])  # 2 équipes -> symétrie


def test_centered_quality_empty_without_squads():
    assert sq.centered_quality({}) == {}                    # pas d'effectif -> pas de note fabriquée


def test_fetch_failure_propagates_for_walk_forward_to_catch(monkeypatch):
    """FBref indisponible -> exception claire (le walk-forward la capte et
    neutralise le tilt qualité, contrat de dégradation existant)."""
    def broken(**kw):
        raise RuntimeError("FBref : aucune composante joueur récupérée")
    monkeypatch.setattr(sq, "fetch_player_components", broken)
    with pytest.raises(RuntimeError, match="aucune composante"):
        sq.centered_quality({"France": _squad(("X", 90))})


# --- Anti rate-limit FBref (délai inter-ligues, retry/backoff, skip) ---------

def _patch_fbref(monkeypatch, behaviour):
    """Patch player_data.fetch_player_season_components + time.sleep (enregistrés).

    `behaviour(league_key, call_count)` -> list[dict] (rows) ou lève.
    Retourne (sleeps, calls) accumulés.
    """
    from engine import player_data

    sleeps: list[float] = []
    calls: list[str] = []

    def fake_fetch(leagues, seasons, competition_label, is_national):
        calls.append(leagues)
        return behaviour(leagues, calls.count(leagues))

    monkeypatch.setattr(player_data, "fetch_player_season_components", fake_fetch)
    monkeypatch.setattr(player_data, "components_per90_adjusted", lambda rows: rows)
    monkeypatch.setattr(sq.time, "sleep", lambda s: sleeps.append(s))
    return sleeps, calls


def test_delay_between_leagues(monkeypatch):
    """Un délai explicite est appliqué ENTRE les ligues (pas avant la 1re)."""
    sleeps, calls = _patch_fbref(
        monkeypatch, lambda lg, n: [{"player": f"P-{lg}", "nineties": 10.0}])
    leagues = {"L1": "Ligue 1", "L2": "Premier League", "L3": "La Liga"}
    view = sq.fetch_player_components(leagues=leagues, seasons="2526")
    assert len(view) == 3
    assert sleeps == [sq.FBREF_LEAGUE_DELAY_S] * 2          # 3 ligues -> 2 pauses
    assert sq.FBREF_LEAGUE_DELAY_S >= 5.0                    # « plusieurs secondes »


def test_league_failure_retried_with_backoff_then_skipped(monkeypatch):
    """Une ligue en échec permanent est réessayée avec backoff puis SAUTÉE —
    sans bloquer les autres ligues."""
    def behaviour(lg, n):
        if lg == "BAD":
            raise ConnectionError("Could not retrieve page content (CAPTCHA)")
        return [{"player": f"P-{lg}", "nineties": 10.0}]

    sleeps, calls = _patch_fbref(monkeypatch, behaviour)
    view = sq.fetch_player_components(
        leagues={"OK1": "Ligue 1", "BAD": "Serie A", "OK2": "La Liga"}, seasons="2526")

    assert {r["player"] for r in view} == {"P-OK1", "P-OK2"}     # BAD sautée, autres OK
    assert calls.count("BAD") == 1 + sq.FBREF_MAX_RETRIES        # retries épuisés
    # Backoff : attentes croissantes (base, base*2, …) présentes dans les sleeps.
    expected_backoffs = [sq.FBREF_BACKOFF_BASE_S * (2 ** k)
                         for k in range(sq.FBREF_MAX_RETRIES)]
    for wait in expected_backoffs:
        assert wait in sleeps


def test_transient_failure_recovers_on_retry(monkeypatch):
    """Échec transitoire (1er appel) -> le retry suffit, la ligue est gardée."""
    def behaviour(lg, n):
        if n == 1:
            raise ConnectionError("IP block temporaire")
        return [{"player": f"P-{lg}", "nineties": 10.0}]

    sleeps, calls = _patch_fbref(monkeypatch, behaviour)
    view = sq.fetch_player_components(leagues={"L": "Ligue 1"}, seasons="2526")
    assert [r["player"] for r in view] == ["P-L"]
    assert calls.count("L") == 2                              # échec puis succès


def test_all_leagues_failing_raises_clear_error(monkeypatch):
    """Toutes les ligues en échec -> erreur claire (captée par le walk-forward)."""
    def behaviour(lg, n):
        raise ConnectionError("CAPTCHA")

    _patch_fbref(monkeypatch, behaviour)
    with pytest.raises(RuntimeError, match="aucune composante joueur récupérée"):
        sq.fetch_player_components(leagues={"A": "Ligue 1", "B": "La Liga"},
                                   seasons="2526")


def test_empty_rows_treated_as_failure(monkeypatch):
    """[] (tous les stat_types en échec côté player_data) = échec -> retry puis skip."""
    sleeps, calls = _patch_fbref(monkeypatch, lambda lg, n: [])
    with pytest.raises(RuntimeError):
        sq.fetch_player_components(leagues={"L": "Ligue 1"}, seasons="2526")
    assert calls.count("L") == 1 + sq.FBREF_MAX_RETRIES


# --- Branchement couplage (qualité) ---------------------------------------

def test_quality_off_is_identity():
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=2.0, qual_away=-2.0, layer_on=False)
    assert (lh, la) == (1.5, 1.0) and not info["layer_applied"]


def test_quality_only_tilts_without_form():
    # Séparabilité : qualité seule (notes=None) incline quand même les λ.
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=1.5, qual_away=-1.5, layer_on=True)
    assert info["layer_applied"] and info["quality_applied"] and not info["form_applied"]
    assert lh > 1.5 and la < 1.0


def test_equal_quality_is_neutral():
    lh, la, info = coupling.adjusted_lambdas(1.5, 1.0, None, None,
                                             qual_home=0.7, qual_away=0.7, layer_on=True)
    assert info["tilt_home"] == pytest.approx(0.0)
    assert lh == pytest.approx(1.5) and la == pytest.approx(1.0)


def test_quality_bounded():
    """Même une qualité énorme reste bornée par w·CLIP (ne domine jamais)."""
    base = 1.5
    bound = config.PLAYER_TILT_WEIGHT * config.PLAYER_TILT_CLIP
    lh, la, _ = coupling.adjusted_lambdas(base, base, None, None,
                                          qual_home=100.0, qual_away=-100.0, layer_on=True)
    assert abs(lh - base) <= base * bound + 1e-9
    assert abs(la - base) <= base * bound + 1e-9


def test_form_and_quality_separable_and_additive():
    notes_h = TeamNotes(attack=1.0, mid=0.0, defense=0.0, n_players=11)
    notes_a = TeamNotes(attack=0.0, mid=0.0, defense=0.0, n_players=11)
    # forme seule
    _, _, f = coupling.adjusted_lambdas(1.5, 1.0, notes_h, notes_a, ref=REF, layer_on=True)
    # forme + qualité (qualité home supérieure) -> tilt_home encore plus haut
    _, _, fq = coupling.adjusted_lambdas(1.5, 1.0, notes_h, notes_a, ref=REF,
                                         qual_home=1.0, qual_away=-1.0, layer_on=True)
    assert f["form_applied"] and not f["quality_applied"]
    assert fq["form_applied"] and fq["quality_applied"]
    assert fq["tilt_home"] > f["tilt_home"]
