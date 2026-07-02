"""Correction 3 — standardisation des composantes avant combinaison.

Sous l'ancienne somme brute, un « passeur » (gros compteurs de passes) battait à
tort un « finisseur » (buts/xG décisifs mais peu de passes). Après z-score +
poids, le finisseur repasse devant. On vérifie aussi : note ≈ 0 pour un joueur à
la moyenne de population, et aucune division par zéro / NaN sur écart-type nul.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

import config
from engine.player_form import (PlayerMatchStore, ComponentNormalizer, note_joueur)

DATE_REF = config.WC2026_START
PLAY_DATE = DATE_REF - dt.timedelta(days=30)   # match < cutoff (pré-tournoi)


def _row(player, **stats):
    base = dict(player=player, date=PLAY_DATE, competition="Premier League",
                is_national=False, minutes=90,
                goals=0.0, xg=0.0, assists=0.0, xa=0.0, key_passes=0.0, chances_created=0.0,
                prog_passes=0.0, recoveries=0.0, pass_pct_pressure=0.0,
                tackles=0.0, interceptions=0.0, duels_won=0.0, clearances=0.0, xg_against=0.0)
    base.update(stats)
    return base


def _population():
    """5 joueurs « filler » avec un étalement sur buts/xG et passes clés/occasions."""
    rows = []
    for i in range(5):
        rows.append(_row(f"filler{i}",
                         goals=i * 0.1, xg=i * 0.1,
                         key_passes=float(i + 1), chances_created=float(i + 1)))
    return pd.DataFrame(rows)


def _mean(series_name, pop):
    return float(pop[series_name].mean())


def test_finisher_beats_passer_after_standardization():
    pop = _population()
    normalizer = ComponentNormalizer.fit(PlayerMatchStore.from_dataframe(pop),
                                          cutoff=DATE_REF)
    # Finisseur : buts/xG élevés, passes moyennes. Passeur : buts moyens, passes hautes.
    players = PlayerMatchStore.from_dataframe(pd.DataFrame([
        _row("Finisher", goals=0.8, xg=0.8, key_passes=3.0, chances_created=3.0),
        _row("Passeur", goals=0.2, xg=0.2, key_passes=8.0, chances_created=8.0),
    ]))
    nf = note_joueur("Finisher", DATE_REF, players, normalizer)
    npa = note_joueur("Passeur", DATE_REF, players, normalizer)
    assert nf is not None and npa is not None
    assert nf.attack > npa.attack   # le décisif passe devant le « toucheur de ballon »


def test_population_mean_player_scores_near_zero():
    pop = _population()
    normalizer = ComponentNormalizer.fit(PlayerMatchStore.from_dataframe(pop),
                                          cutoff=DATE_REF)
    avg = PlayerMatchStore.from_dataframe(pd.DataFrame([
        _row("Avg", goals=_mean("goals", pop), xg=_mean("xg", pop),
             key_passes=_mean("key_passes", pop),
             chances_created=_mean("chances_created", pop)),
    ]))
    note = note_joueur("Avg", DATE_REF, avg, normalizer)
    assert note is not None
    assert abs(note.attack) < 1e-9   # exactement à la moyenne -> z = 0 partout


def test_zero_std_component_no_div_zero_no_nan():
    # assists/xa sont 0 pour toute la population -> écart-type nul -> z = 0, pas de NaN.
    pop = _population()
    normalizer = ComponentNormalizer.fit(PlayerMatchStore.from_dataframe(pop),
                                          cutoff=DATE_REF)
    assert normalizer.stds["assists"] == 0.0
    assert normalizer.z("assists", 5.0) == 0.0   # pas de division par zéro
    players = PlayerMatchStore.from_dataframe(pd.DataFrame([
        _row("P", goals=0.5, assists=9.0, xa=9.0),
    ]))
    note = note_joueur("P", DATE_REF, players, normalizer)
    import math
    assert note is not None
    for v in (note.attack, note.mid, note.defense):
        assert not math.isnan(v)
