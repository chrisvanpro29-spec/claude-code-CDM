"""Module 4 — Validation walk-forward (brief §6). LE juge.

Replay chronologique des matchs CDM 2026 déjà joués :
  1. baseline équipe **gelée** (fit une seule fois sur l'historique < coup d'envoi
     du tournoi — les matchs CDM ne fittent JAMAIS la baseline, §1.3) ;
  2. à chaque match : proba modèle (couche OFF puis ON) avec date_ref = coup
     d'envoi (la couche joueur ne voit que le passé via note_joueur) ;
  3. comparaison au marché (G) quand un snapshot d'avant-match est disponible ;
  4. métriques pré-enregistrées : Brier, log-loss, reliability diagram ;
  5. ablation OFF vs ON — on ne garde la couche joueur que si elle améliore le
     Brier out-of-sample. Aucun re-tuning après avoir vu les métriques.

Usage : python -m validation.walk_forward
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import config
from audit.paths import DATA_DIR
from engine import data, coupling
from engine.team_model import DixonColesModel
from engine.player_form import PlayerMatchStore, SquadPlayer, team_notes
from . import metrics

OUT_DIR = DATA_DIR / "validation"
SNAP_DIR = DATA_DIR / "raw" / "market_snapshots"

OUTCOME_HOME, OUTCOME_DRAW, OUTCOME_AWAY = 0, 1, 2


# ---------------------------------------------------------------------------
# Données joueur / marché (vides par défaut dans cet environnement -> dégradation
# honnête, jamais de note fabriquée).
# ---------------------------------------------------------------------------

def load_player_store() -> PlayerMatchStore:
    """Charge les journaux de matchs joueur si disponibles ; sinon store vide."""
    pdir = DATA_DIR / "raw" / "players"
    frames = []
    if pdir.exists():
        for f in sorted(pdir.glob("*.parquet")):
            frames.append(pd.read_parquet(f))
        for f in sorted(pdir.glob("*.csv")):
            frames.append(pd.read_csv(f))
    if frames:
        return PlayerMatchStore.from_dataframe(pd.concat(frames, ignore_index=True))
    return PlayerMatchStore()  # vide


def load_squads() -> dict[str, list[SquadPlayer]]:
    """Charge les onze probables {équipe: [SquadPlayer]} si disponibles ; sinon {}."""
    f = DATA_DIR / "raw" / "squads.json"
    if not f.exists():
        return {}
    raw = json.loads(f.read_text(encoding="utf-8"))
    return {team: [SquadPlayer(**p) for p in players] for team, players in raw.items()}


def load_market_snapshots() -> dict[tuple, np.ndarray]:
    """Snapshots marché d'avant-match : {(date, home, away): [pH,pD,pA] dévigé}."""
    snaps: dict[tuple, np.ndarray] = {}
    if not SNAP_DIR.exists():
        return snaps
    for f in sorted(SNAP_DIR.glob("*.json")):
        for ev in json.loads(f.read_text(encoding="utf-8")):
            key = (str(ev["date"]), ev["home_team"], ev["away_team"])
            p = np.array([ev["p_home"], ev["p_draw"], ev["p_away"]], dtype=float)
            s = p.sum()
            if s > 0:
                snaps[key] = p / s
    return snaps


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _probs_vector(p: dict) -> np.ndarray:
    return np.array([p["p_home"], p["p_draw"], p["p_away"]], dtype=float)


def _outcome(home_score: float, away_score: float) -> int:
    if home_score > away_score:
        return OUTCOME_HOME
    if home_score < away_score:
        return OUTCOME_AWAY
    return OUTCOME_DRAW


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Baseline gelée (fit unique sur l'historique strictement avant le tournoi).
    print("[walk-forward] fit baseline Dixon-Coles (gelée, < coup d'envoi CDM)…")
    model = DixonColesModel().fit(as_of=config.WC2026_START, verbose=True)

    store = load_player_store()
    squads = load_squads()
    market = load_market_snapshots()

    test = data.wc2026_matches(played_only=True)
    print(f"[walk-forward] {len(test)} matchs CDM 2026 joués à rejouer.")

    rows = []
    probs_off, probs_on, probs_mkt = [], [], []
    outcomes, outcomes_mkt = [], []
    layer_applied = 0

    for r in test.itertuples(index=False):
        date_ref = r.date
        home, away = r.home_team, r.away_team
        neutral = bool(r.neutral)
        y = _outcome(r.home_score, r.away_score)

        # Couche OFF (équipe seule).
        lam_h, lam_a = model.lambdas(home, away, neutral)
        p_off = model.match_probabilities(home, away, neutral, lambdas=(lam_h, lam_a))

        # Couche ON : notes équipe à date_ref (fenêtre glissante via note_joueur).
        nh = team_notes(squads.get(home, []), date_ref, store) if squads else None
        na = team_notes(squads.get(away, []), date_ref, store) if squads else None
        lh2, la2, info = coupling.adjusted_lambdas(lam_h, lam_a, nh, na, layer_on=True)
        if info["layer_applied"]:
            layer_applied += 1
        p_on = model.match_probabilities(home, away, neutral, lambdas=(lh2, la2))

        probs_off.append(_probs_vector(p_off))
        probs_on.append(_probs_vector(p_on))
        outcomes.append(y)

        key = (str(date_ref), home, away)
        mkt = market.get(key)
        if mkt is not None:
            probs_mkt.append(mkt)
            outcomes_mkt.append(y)

        rows.append({
            "date": str(date_ref), "home": home, "away": away,
            "score": f"{int(r.home_score)}-{int(r.away_score)}",
            "outcome": ["H", "D", "A"][y],
            "p_off": [round(float(x), 3) for x in _probs_vector(p_off)],
            "p_on": [round(float(x), 3) for x in _probs_vector(p_on)],
            "layer": info["reason"],
        })

    probs_off = np.array(probs_off); probs_on = np.array(probs_on)
    outcomes = np.array(outcomes)

    result = {
        "n_test": len(test),
        "layer_applied": layer_applied,
        "brier_off": metrics.brier_multiclass(probs_off, outcomes),
        "brier_on": metrics.brier_multiclass(probs_on, outcomes),
        "logloss_off": metrics.log_loss_multiclass(probs_off, outcomes),
        "logloss_on": metrics.log_loss_multiclass(probs_on, outcomes),
        "rows": rows,
    }

    if probs_mkt:
        pm = np.array(probs_mkt); om = np.array(outcomes_mkt)
        # comparer modèle et marché sur le MÊME sous-ensemble couvert.
        mask = np.array([(str(rw["date"]), rw["home"], rw["away"]) in market for rw in rows])
        result.update({
            "n_market": len(pm),
            "brier_market": metrics.brier_multiclass(pm, om),
            "brier_off_on_market_subset": metrics.brier_multiclass(probs_off[mask], outcomes[mask]),
            "brier_on_on_market_subset": metrics.brier_multiclass(probs_on[mask], outcomes[mask]),
        })
    else:
        result["n_market"] = 0

    _plot_reliability(probs_off, probs_on, outcomes,
                      np.array(probs_mkt) if probs_mkt else None,
                      np.array(outcomes_mkt) if probs_mkt else None)
    _write_report(result)
    _print_verdict(result)
    return result


def _plot_reliability(p_off, p_on, y, p_mkt, y_mkt) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="calibration parfaite")

    for probs, outc, label, style in [
        (p_off, y, "modèle OFF (équipe)", "o-"),
        (p_on, y, "modèle ON (équipe+joueur)", "s-"),
    ]:
        pr, hit = metrics.flatten_ovr(probs, outc)
        mp, fo, _ = metrics.reliability_curve(pr, hit)
        m = ~np.isnan(mp)
        ax.plot(mp[m], fo[m], style, label=label)

    if p_mkt is not None and len(p_mkt):
        pr, hit = metrics.flatten_ovr(p_mkt, y_mkt)
        mp, fo, _ = metrics.reliability_curve(pr, hit)
        m = ~np.isnan(mp)
        ax.plot(mp[m], fo[m], "^-", label="marché (juge)")

    ax.set_xlabel("probabilité prédite"); ax.set_ylabel("fréquence observée")
    ax.set_title("Reliability diagram — CDM 2026 (one-vs-rest 1X2)")
    ax.legend(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    out = OUT_DIR / "reliability.png"
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)
    print(f"[walk-forward] reliability diagram -> {out}")


def _write_report(res: dict) -> None:
    lines = ["# Validation walk-forward — CDM 2026", ""]
    lines.append(f"- Matchs de test (joués, out-of-sample) : **{res['n_test']}**")
    lines.append(f"- Matchs où la couche joueur a été appliquée : **{res['layer_applied']}** "
                 f"/ {res['n_test']}")
    lines.append("")
    lines.append("## Métriques (plus petit = mieux)")
    lines.append("")
    lines.append("| Métrique | Couche OFF | Couche ON |")
    lines.append("|---|---|---|")
    lines.append(f"| Brier (1X2) | {res['brier_off']:.4f} | {res['brier_on']:.4f} |")
    lines.append(f"| Log-loss (1X2) | {res['logloss_off']:.4f} | {res['logloss_on']:.4f} |")
    lines.append("")
    if res.get("n_market", 0) > 0:
        lines.append(f"## Vs marché (sous-ensemble couvert : {res['n_market']} matchs)")
        lines.append("")
        lines.append(f"- Brier marché : **{res['brier_market']:.4f}**")
        lines.append(f"- Brier modèle OFF (même sous-ensemble) : {res['brier_off_on_market_subset']:.4f}")
        lines.append(f"- Brier modèle ON (même sous-ensemble) : {res['brier_on_on_market_subset']:.4f}")
    else:
        lines.append("## Vs marché")
        lines.append("")
        lines.append("Aucun snapshot marché d'avant-match disponible pour les matchs déjà "
                     "joués (the-odds-api ne renvoie pas de cotes rétroactives). Capturer "
                     "les lignes via un snapshot avant chaque match à venir pour activer "
                     "cette comparaison.")
    lines.append("")
    lines.append(_verdict_text(res))
    lines.append("")
    lines.append("## Détail par match")
    lines.append("")
    lines.append("| Date | Match | Score | Issue | P(H,D,A) OFF | P(H,D,A) ON |")
    lines.append("|---|---|---|---|---|---|")
    for rw in res["rows"]:
        lines.append(f"| {rw['date']} | {rw['home']} – {rw['away']} | {rw['score']} | "
                     f"{rw['outcome']} | {rw['p_off']} | {rw['p_on']} |")
    (OUT_DIR / "walk_forward_report.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "walk_forward.json").write_text(
        json.dumps({k: v for k, v in res.items() if k != "rows"} | {"rows": res["rows"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[walk-forward] rapport -> {OUT_DIR / 'walk_forward_report.md'}")


def _verdict_text(res: dict) -> str:
    if res["layer_applied"] == 0:
        return ("## Verdict\n\n**Couche joueur inactive** : 0 match couvert (données joueur "
                "FBref/Understat indisponibles dans cet environnement — cf. audit, sources "
                "fragiles). OFF et ON sont donc identiques. On ne peut PAS confirmer une "
                "amélioration → la couche reste **coupée** tant que la donnée joueur n'est pas "
                "branchée. (Le mécanisme est testé et prêt : cf. tests/test_no_lookahead.)")
    improved = res["brier_on"] < res["brier_off"]
    delta = res["brier_off"] - res["brier_on"]
    if improved:
        return (f"## Verdict\n\n**La couche joueur améliore la calibration** : Brier "
                f"{res['brier_off']:.4f} → {res['brier_on']:.4f} (Δ = {delta:+.4f}). "
                "On la garde.")
    return (f"## Verdict\n\n**La couche joueur n'améliore pas le Brier** "
            f"({res['brier_off']:.4f} → {res['brier_on']:.4f}, Δ = {delta:+.4f}) : "
            "c'est du bruit, on la coupe — sans se mentir.")


def _print_verdict(res: dict) -> None:
    print("=" * 60)
    print(f"Brier   OFF={res['brier_off']:.4f}  ON={res['brier_on']:.4f}")
    print(f"LogLoss OFF={res['logloss_off']:.4f}  ON={res['logloss_on']:.4f}")
    if res.get("n_market", 0) > 0:
        print(f"Brier marché={res['brier_market']:.4f} (sur {res['n_market']} matchs)")
    print(_verdict_text(res).replace("## Verdict\n\n", "VERDICT: ").replace("**", ""))


if __name__ == "__main__":
    run()
