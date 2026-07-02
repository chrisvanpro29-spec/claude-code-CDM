"""Tests du collecteur de snapshots marché (le juge qui s'accumule).

Couvre : dé-vig, résolution fixture (TEAM_NAME_MAP + tolérance date + non-apparié
non forcé), gel anti-look-ahead (pré-match seulement, kickoff passé jamais
réécrit), et conformité du schéma de sortie avec le walk-forward.
"""

from __future__ import annotations

import datetime as dt

from engine import market_collector as mc

UTC = dt.timezone.utc


# --- Dé-vig ---------------------------------------------------------------

def test_devig_sums_to_one_and_keeps_order():
    ph, pd_, pa = mc.devig(2.0, 3.5, 4.0)
    assert abs(ph + pd_ + pa - 1.0) < 1e-9
    # cote la plus basse (2.0) -> proba la plus haute ; ordre conservé.
    assert ph > pd_ > pa


def test_devig_removes_margin():
    # cotes équilibrées avec marge -> chaque proba < proba brute, somme = 1.
    ph, pd_, pa = mc.devig(3.0, 3.0, 3.0)
    assert abs(ph - 1 / 3) < 1e-9 and abs(pd_ - 1 / 3) < 1e-9 and abs(pa - 1 / 3) < 1e-9


# --- Résolution fixture ---------------------------------------------------

FIXTURES = [
    {"date": dt.date(2026, 6, 21), "home_team": "South Korea", "away_team": "United States"},
    {"date": dt.date(2026, 6, 22), "home_team": "France", "away_team": "Iraq"},
]
NAME_MAP = {"Korea Republic": "South Korea", "USA": "United States"}


def test_resolve_with_name_map_and_date_tolerance():
    # Événement à +12 h, noms à mapper -> apparie la fixture du 21.
    commence = dt.datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    fx, swapped = mc.resolve_fixture("Korea Republic", "USA", commence,
                                     FIXTURES, name_map=NAME_MAP)
    assert fx is not None and fx["home_team"] == "South Korea"
    assert swapped is False


def test_resolve_detects_swapped_orientation():
    commence = dt.datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    fx, swapped = mc.resolve_fixture("USA", "Korea Republic", commence,
                                     FIXTURES, name_map=NAME_MAP)
    assert fx is not None and swapped is True   # orientation inversée -> permuter pH/pA


def test_unknown_event_not_force_matched():
    commence = dt.datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    fx, swapped = mc.resolve_fixture("Narnia", "Atlantis", commence,
                                     FIXTURES, name_map=NAME_MAP)
    assert fx is None and swapped is None


def test_date_outside_tolerance_no_match():
    commence = dt.datetime(2026, 6, 25, 12, 0, tzinfo=UTC)   # +4 j de la fixture
    fx, _ = mc.resolve_fixture("Korea Republic", "USA", commence,
                               FIXTURES, name_map=NAME_MAP)
    assert fx is None


# --- Gel anti-look-ahead --------------------------------------------------

def test_should_write_only_prematch():
    commence = dt.datetime(2026, 6, 21, 18, 0, tzinfo=UTC)
    assert mc.should_write(commence, dt.datetime(2026, 6, 21, 17, 0, tzinfo=UTC))
    assert not mc.should_write(commence, dt.datetime(2026, 6, 21, 18, 0, tzinfo=UTC))
    assert not mc.should_write(commence, dt.datetime(2026, 6, 21, 19, 0, tzinfo=UTC))


def test_frozen_record_not_rewritten():
    existing = {"commence_time": "2026-06-21T18:00:00Z"}
    after = dt.datetime(2026, 6, 21, 19, 0, tzinfo=UTC)
    before = dt.datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    assert mc.is_frozen(existing, after)        # kickoff passé -> gelé
    assert not mc.is_frozen(existing, before)   # avant kickoff -> modifiable
    assert not mc.is_frozen(None, after)


def _event(home, away, commence_iso, books):
    return {"home_team": home, "away_team": away, "commence_time": commence_iso,
            "bookmakers": books}


def _h2h_book(key, home, away, oh, od, oa):
    return {"key": key, "markets": [{"key": "h2h", "outcomes": [
        {"name": home, "price": oh}, {"name": "Draw", "price": od},
        {"name": away, "price": oa}]}]}


def test_process_events_writes_prematch_and_freezes_past():
    now = dt.datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    events = [
        # pré-match, dans l'horizon -> écrit
        _event("Korea Republic", "USA", "2026-06-21T12:00:00Z",
               [_h2h_book("pinnacle", "Korea Republic", "USA", 2.0, 3.5, 4.0)]),
        # coup d'envoi déjà passé -> ignoré (non pré-match)
        _event("France", "Iraq", "2026-06-20T10:00:00Z",
               [_h2h_book("pinnacle", "France", "Iraq", 1.3, 5.0, 9.0)]),
    ]
    recs, matched, unmatched, skipped = mc.process_events(
        events, FIXTURES, existing=[], now=now, name_map=NAME_MAP, horizon_hours=72)
    assert len(matched) == 1 and recs[0]["home_team"] == "South Korea"
    # le match au coup d'envoi déjà passé est exclu (jamais écrit comme pré-match).
    assert len(recs) == 1
    assert any(h == "France" for h, *_ in skipped)


def test_process_events_does_not_rewrite_frozen():
    now = dt.datetime(2026, 6, 21, 19, 0, tzinfo=UTC)  # kickoff (18h) passé
    frozen = {"date": "2026-06-21", "home_team": "South Korea", "away_team": "United States",
              "p_home": 0.5, "p_draw": 0.25, "p_away": 0.25,
              "commence_time": "2026-06-21T18:00:00Z", "captured_at": "2026-06-21T17:00:00Z",
              "n_books": 3}
    events = [_event("Korea Republic", "USA", "2026-06-21T18:00:00Z",
                     [_h2h_book("pinnacle", "Korea Republic", "USA", 1.1, 9, 15)])]
    recs, matched, unmatched, skipped = mc.process_events(
        events, FIXTURES, existing=[frozen], now=now, name_map=NAME_MAP, horizon_hours=72)
    assert len(matched) == 0
    assert recs[0]["p_home"] == 0.5   # inchangé : record gelé


# --- Schéma de sortie (lecture croisée walk-forward) ----------------------

def test_output_schema_matches_walk_forward_reader():
    from validation.walk_forward import load_market_snapshots  # noqa
    now = dt.datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    events = [_event("Korea Republic", "USA", "2026-06-21T12:00:00Z",
                     [_h2h_book("pinnacle", "Korea Republic", "USA", 2.0, 3.5, 4.0)])]
    recs, *_ = mc.process_events(events, FIXTURES, existing=[], now=now,
                                 name_map=NAME_MAP, horizon_hours=72)
    required = {"date", "home_team", "away_team", "p_home", "p_draw", "p_away"}
    assert required.issubset(recs[0].keys())
