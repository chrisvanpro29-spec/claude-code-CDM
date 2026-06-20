"""Module 3 — Simulation Monte Carlo du tournoi (brief §5).

Phase de groupes simulée **au format réel** de la CDM 2026 (12 groupes de 4 ;
qualifiés = 2 premiers de chaque groupe + 8 meilleurs troisièmes). La phase à
élimination directe est simulée sur les 32 qualifiés via une tête de série Elo et
des probabilités de victoire par paire (approximation documentée : l'appariement
exact du bracket FIFA n'est pas reproduit — la qualité du moteur, si).

Seed fixé (config.MC_SEED) pour la reproductibilité.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from . import elo as elo_mod
from .team_model import DixonColesModel

GROUP_STAGE_END = None  # toutes les dates du label WC sont en phase de groupes ici


def infer_groups(fixtures: pd.DataFrame) -> list[list[str]]:
    """Reconstruit les groupes : le groupe d'une équipe = elle + ses 3 adversaires.

    Dans un groupe de 4, chacun affronte les 3 autres -> les adversaires d'une
    équipe en phase de groupes forment exactement son groupe.
    """
    opp: dict[str, set[str]] = {}
    for r in fixtures.itertuples(index=False):
        opp.setdefault(r.home_team, set()).add(r.away_team)
        opp.setdefault(r.away_team, set()).add(r.home_team)
    seen: set[str] = set()
    groups: list[list[str]] = []
    for team, adv in opp.items():
        if team in seen:
            continue
        grp = sorted({team} | adv)
        seen.update(grp)
        groups.append(grp)
    return groups


def _fixture_score_distribution(model: DixonColesModel, home: str, away: str,
                                neutral: bool) -> np.ndarray:
    """Vecteur de probabilités aplati (121,) de la matrice de scores d'un match."""
    lam_h, lam_a = model.lambdas(home, away, neutral)
    return model.score_matrix(lam_h, lam_a).ravel()


def _pairwise_win_matrix(model: DixonColesModel, teams: list[str]) -> np.ndarray:
    """P[i,j] = proba que i batte j en match à élimination directe (penalty = pile/face)."""
    n = len(teams)
    pw = np.full((n, n), 0.5)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            p = model.match_probabilities(teams[i], teams[j], neutral=True)
            pw[i, j] = p["p_home"] + 0.5 * p["p_draw"]
    return pw


def simulate(model: DixonColesModel, fixtures: pd.DataFrame,
             n_sims: int | None = None, seed: int | None = None) -> dict:
    """Lance la simulation Monte Carlo et renvoie les probabilités agrégées.

    Retour : {'advance': {team: p}, 'win_group': {...}, 'title': {team: p}, ...}.
    """
    n_sims = n_sims or config.MC_N_SIMS
    rng = np.random.default_rng(seed if seed is not None else config.MC_SEED)

    groups = infer_groups(fixtures)
    teams = sorted({t for g in groups for t in g})
    tidx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)

    # Elo (tête de série pour le bracket à élimination directe).
    ratings = elo_mod.compute_elo()
    elo_arr = np.array([ratings.get(t, config.ELO_BASE) for t in teams])

    # Accumulateurs.
    advance_count = np.zeros(n_teams)
    wingroup_count = np.zeros(n_teams)
    title_count = np.zeros(n_teams)

    # Pré-calcul des distributions de score par fixture de groupe.
    fx = fixtures[["home_team", "away_team", "neutral"]].copy()
    fx_dist = [
        (tidx[r.home_team], tidx[r.away_team],
         _fixture_score_distribution(model, r.home_team, r.away_team, bool(r.neutral)))
        for r in fx.itertuples(index=False)
    ]
    # Map groupe -> indices d'équipes et de fixtures.
    group_team_idx = [[tidx[t] for t in g] for g in groups]
    group_fx = []
    for g in groups:
        gi = set(tidx[t] for t in g)
        group_fx.append([k for k, (h, a, _) in enumerate(fx_dist) if h in gi and a in gi])

    pw = _pairwise_win_matrix(model, teams)

    # On simule par blocs pour limiter la mémoire.
    BLOCK = 5000
    done = 0
    while done < n_sims:
        b = min(BLOCK, n_sims - done)

        # 1) Échantillonner tous les scores de fixtures (b, n_fixtures).
        hs = np.zeros((b, len(fx_dist)), dtype=int)
        as_ = np.zeros((b, len(fx_dist)), dtype=int)
        for k, (_, _, dist) in enumerate(fx_dist):
            draws = rng.choice(121, size=b, p=dist)
            hs[:, k] = draws // 11
            as_[:, k] = draws % 11

        # 2) Classement de chaque groupe -> qualifiés (top 2) + 3e.
        # points, gd, gf par équipe et par sim.
        pts = np.zeros((b, n_teams)); gf = np.zeros((b, n_teams)); ga = np.zeros((b, n_teams))
        for k, (h, a, _) in enumerate(fx_dist):
            hsc, asc = hs[:, k], as_[:, k]
            gf[:, h] += hsc; ga[:, h] += asc
            gf[:, a] += asc; ga[:, a] += hsc
            home_win = hsc > asc; away_win = asc > hsc; draw = hsc == asc
            pts[:, h] += 3 * home_win + 1 * draw
            pts[:, a] += 3 * away_win + 1 * draw
        gd = gf - ga

        thirds_idx = []      # (sim, team_idx, score) pour départager les 3es
        winners_runners = np.zeros((b, n_teams), dtype=bool)
        for g_idx, gteams in enumerate(group_team_idx):
            gt = np.array(gteams)
            # score de classement : points, puis diff, puis buts (lexicographique).
            key = (pts[:, gt] * 1e6 + gd[:, gt] * 1e3 + gf[:, gt]
                   + rng.random((b, len(gt))) * 1e-3)  # bruit -> départage aléatoire
            order = np.argsort(-key, axis=1)
            first = gt[order[:, 0]]; second = gt[order[:, 1]]; third = gt[order[:, 2]]
            rows = np.arange(b)
            winners_runners[rows, first] = True
            winners_runners[rows, second] = True
            wingroup_count_local = first
            np.add.at(wingroup_count, wingroup_count_local, 1)
            np.add.at(advance_count, first, 1)
            np.add.at(advance_count, second, 1)
            third_key = pts[rows, third] * 1e6 + gd[rows, third] * 1e3 + gf[rows, third]
            thirds_idx.append((third, third_key))

        # 3) 8 meilleurs troisièmes (sur 12) -> qualifiés.
        third_teams = np.stack([t for t, _ in thirds_idx], axis=1)        # (b, 12)
        third_keys = np.stack([k for _, k in thirds_idx], axis=1)         # (b, 12)
        best_thirds_order = np.argsort(-third_keys, axis=1)[:, :8]
        qualifiers = np.zeros((b, 32), dtype=int)
        # 24 premiers/deuxièmes + 8 meilleurs 3es par sim.
        for s in range(b):
            wr = np.where(winners_runners[s])[0]
            bt = third_teams[s, best_thirds_order[s]]
            qualifiers[s] = np.concatenate([wr, bt])
            np.add.at(advance_count, bt, 1)

        # 4) Élimination directe : tête de série Elo -> bracket standard 1..32.
        champ = _knockout(qualifiers, elo_arr, pw, rng)
        np.add.at(title_count, champ, 1)

        done += b

    def as_prob(arr):
        return {teams[i]: float(arr[i] / n_sims) for i in range(n_teams)}

    return {
        "n_sims": n_sims,
        "teams": teams,
        "advance": as_prob(advance_count),
        "win_group": as_prob(wingroup_count),
        "title": as_prob(title_count),
    }


def _knockout(qualifiers: np.ndarray, elo_arr: np.ndarray, pw: np.ndarray,
              rng: np.random.Generator) -> np.ndarray:
    """Simule l'élimination directe (vectorisé par sim). Retourne l'index du champion."""
    b = qualifiers.shape[0]
    # Tête de série : trier les 32 qualifiés par Elo décroissant, puis bracket 1v32...
    elo_of = elo_arr[qualifiers]                          # (b, 32)
    seed_order = np.argsort(-elo_of, axis=1)              # meilleurs d'abord
    seeded = np.take_along_axis(qualifiers, seed_order, axis=1)
    # Appariement standard : 1-32, 16-17, 8-25, ... -> on génère l'ordre des slots.
    slot_order = _standard_seeding(32)
    bracket = seeded[:, slot_order]                       # (b, 32) prêts à s'affronter par paires

    alive = bracket
    while alive.shape[1] > 1:
        left = alive[:, 0::2]; right = alive[:, 1::2]
        p_left = pw[left, right]
        u = rng.random(p_left.shape)
        winners = np.where(u < p_left, left, right)
        alive = winners
    return alive[:, 0]


def _standard_seeding(n: int) -> list[int]:
    """Ordre des positions pour un bracket à élimination directe standard (n = puissance de 2)."""
    seeds = [0, 1]
    while len(seeds) < n:
        m = len(seeds) * 2
        nxt = []
        for s in seeds:
            nxt.append(s)
            nxt.append(m - 1 - s)
        seeds = nxt
    return seeds
