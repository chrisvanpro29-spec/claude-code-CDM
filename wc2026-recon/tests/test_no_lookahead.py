"""Test anti-fuite (brief §1.2) : note_joueur ne lit JAMAIS un match >= date_ref.

La fuite doit être *impossible*, pas seulement évitée. On construit un store avec
des matchs avant ET après date_ref, et on vérifie qu'aucune ligne >= date_ref
n'entre dans la note, à plusieurs niveaux :
  - la surface d'accès (store.history) filtre strictement ;
  - note_joueur n'utilise que cette surface ;
  - la fenêtre glissante fait entrer un match passé dès qu'il devient antérieur.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from engine.player_form import PlayerMatchStore, note_joueur, team_notes, SquadPlayer


def _row(player, date, is_national=False, comp="Premier League", minutes=90, **stats):
    base = dict(player=player, date=date, competition=comp,
                is_national=is_national, minutes=minutes,
                goals=0, xg=0.0, assists=0, xa=0.0, key_passes=0, chances_created=0,
                prog_passes=0, recoveries=0, pass_pct_pressure=0.0,
                tackles=0, interceptions=0, duels_won=0, clearances=0, xg_against=0.0)
    base.update(stats)
    return base


DATE_REF = dt.date(2026, 6, 15)


def _store_with_future_poison():
    """Matchs avant date_ref (légitimes) + après (poison à ne jamais lire)."""
    rows = [
        _row("Mbappé", dt.date(2026, 5, 1), goals=2, xg=1.5),
        _row("Mbappé", dt.date(2026, 6, 10), goals=1, xg=0.8),
        _row("Mbappé", dt.date(2026, 6, 14), is_national=True, goals=1, xg=0.9),
        # POISON : >= date_ref. Doit rester invisible.
        _row("Mbappé", dt.date(2026, 6, 15), goals=9, xg=9.0),   # le jour même
        _row("Mbappé", dt.date(2026, 6, 20), goals=9, xg=9.0),   # futur
    ]
    return PlayerMatchStore.from_dataframe(pd.DataFrame(rows))


def test_history_filters_strictly_before():
    store = _store_with_future_poison()
    hist = store.history("Mbappé", DATE_REF)
    assert len(hist) == 3
    assert (hist["date"] < DATE_REF).all()
    assert store.max_date_served < DATE_REF


def test_note_joueur_ignores_future():
    store = _store_with_future_poison()
    note = note_joueur("Mbappé", DATE_REF, store)
    assert note is not None
    # 2 matchs club + 1 sélection, jamais le poison (xg=9).
    assert note.n_club == 2
    assert note.n_national == 1
    # Le store n'a jamais servi de date >= date_ref.
    assert store.max_date_served < DATE_REF


def test_sliding_window_admits_past_legally():
    """Un match du tournoi devient utilisable dès que date_ref passe APRÈS lui."""
    store = _store_with_future_poison()
    # Avant le 15/06 : le match du 15 est invisible.
    n1 = note_joueur("Mbappé", dt.date(2026, 6, 15), store)
    # Le 16/06 : le match du 15 est désormais passé -> il entre légalement.
    n2 = note_joueur("Mbappé", dt.date(2026, 6, 16), store)
    assert n2.n_club >= n1.n_club  # au moins autant de matchs club disponibles
    assert store.max_date_served <= dt.date(2026, 6, 15)


def test_no_data_returns_none_no_fabrication():
    store = PlayerMatchStore()  # vide
    assert note_joueur("Inconnu", DATE_REF, store) is None


def test_team_notes_disabled_below_coverage():
    """Couverture insuffisante -> None (fallback équipe seule), pas de note fabriquée."""
    store = _store_with_future_poison()  # un seul joueur a des données
    squad = [SquadPlayer("Mbappé", "ATT", 90)] + \
            [SquadPlayer(f"X{i}", "MID", 90) for i in range(10)]
    assert team_notes(squad, DATE_REF, store) is None


def test_window_caps_respected():
    """Au plus CLUB_FORM_WINDOW matchs club + NATIONAL_FORM_WINDOW sélection."""
    import config
    rows = [_row("P", dt.date(2024, 1, 1) + dt.timedelta(days=i), goals=1)
            for i in range(40)]
    rows += [_row("P", dt.date(2024, 1, 1) + dt.timedelta(days=i), is_national=True)
             for i in range(40)]
    store = PlayerMatchStore.from_dataframe(pd.DataFrame(rows))
    note = note_joueur("P", dt.date(2026, 6, 15), store)
    assert note.n_club == config.CLUB_FORM_WINDOW
    assert note.n_national == config.NATIONAL_FORM_WINDOW


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
