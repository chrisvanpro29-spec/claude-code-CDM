"""Collecteur de snapshots marché — le juge qui s'accumule (the-odds-api, source G).

Capture, AVANT chaque match, la ligne 1X2 du marché, la dé-vigge en probabilités,
la résout contre les fixtures connues (jointure exacte garantie), et la stocke
horodatée là où le walk-forward sait déjà la lire (`data/raw/market_snapshots/`).

Chronosensible : un match joué sans snapshot capturé avant le coup d'envoi est
perdu (le tier gratuit ne donne pas l'historique des cotes). Pas de paris : le
marché sert uniquement de juge de calibration.

Usage : python -m engine.market_collector [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics

import requests

import config
from audit.paths import DATA_DIR
from engine import data
from sources.odds_api import BASE, TIMEOUT

CONSENSUS_DIR = DATA_DIR / "raw" / "market_snapshots"
RAW_DIR = DATA_DIR / "raw" / "market_snapshots_raw"
CONSENSUS_FILE = CONSENSUS_DIR / "consensus.json"

UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# Dé-vig & consensus (fonctions pures, testées)
# ---------------------------------------------------------------------------

def devig(odds_home: float, odds_draw: float, odds_away: float) -> tuple[float, float, float]:
    """Dé-vig multiplicatif : p_brut = 1/cote, puis normalisation par la somme."""
    raw = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    s = sum(raw)
    return tuple(x / s for x in raw)  # type: ignore[return-value]


def book_probs(market_outcomes: list[dict], ev_home: str, ev_away: str
               ) -> tuple[float, float, float] | None:
    """Probas dé-viggées d'un bookmaker pour un marché h2h (H, D, A) ; None si incomplet."""
    prices = {o.get("name"): o.get("price") for o in market_outcomes}
    oh, od, oa = prices.get(ev_home), prices.get("Draw"), prices.get(ev_away)
    if not (oh and od and oa) or min(oh, od, oa) <= 0:
        return None
    return devig(oh, od, oa)


def per_book_h2h(bookmakers: list[dict], ev_home: str, ev_away: str
                 ) -> list[tuple[str, tuple[float, float, float]]]:
    """Liste (clé_book, (pH,pD,pA)) pour chaque bookmaker ayant un h2h exploitable."""
    out = []
    for b in bookmakers:
        for m in b.get("markets", []):
            if m.get("key") != "h2h":
                continue
            p = book_probs(m.get("outcomes", []), ev_home, ev_away)
            if p is not None:
                out.append((b.get("key"), p))
    return out


def consensus(per_book: list[tuple[str, tuple[float, float, float]]]
              ) -> tuple[tuple[float, float, float], int]:
    """Consensus marché : exchange sharp si présent, sinon médiane robuste renormalisée.

    Retourne ((pH,pD,pA), n_books).
    """
    if not per_book:
        raise ValueError("aucun bookmaker exploitable")
    by_key = dict(per_book)
    for sharp in config.PREFERRED_SHARP_BOOKS:
        if sharp in by_key:
            return by_key[sharp], len(per_book)
    # Médiane par composante (robuste aux aberrants), puis renormalisation.
    ph = statistics.median(p[0] for _, p in per_book)
    pd_ = statistics.median(p[1] for _, p in per_book)
    pa = statistics.median(p[2] for _, p in per_book)
    s = ph + pd_ + pa
    return (ph / s, pd_ / s, pa / s), len(per_book)


# ---------------------------------------------------------------------------
# Résolution fixture (anti-jointure-ratée)
# ---------------------------------------------------------------------------

def normalize_name(name: str, name_map: dict[str, str] | None = None) -> str:
    name_map = config.TEAM_NAME_MAP if name_map is None else name_map
    return name_map.get(name, name)


def resolve_fixture(ev_home: str, ev_away: str, commence: dt.datetime,
                    fixtures: list[dict], name_map: dict[str, str] | None = None,
                    tol_days: int | None = None):
    """Apparie un événement de cotes à une fixture. Retourne (fixture, swapped) ou (None, None).

    `swapped` = True si l'orientation home/away de l'événement est inversée par
    rapport à la fixture (il faudra alors permuter pH/pA).
    """
    tol_days = config.DATE_MATCH_TOLERANCE_DAYS if tol_days is None else tol_days
    nh, na = normalize_name(ev_home, name_map), normalize_name(ev_away, name_map)
    cdate = commence.astimezone(UTC).date()
    for fx in fixtures:
        if abs((fx["date"] - cdate).days) > tol_days:
            continue
        pair = {fx["home_team"], fx["away_team"]}
        if pair != {nh, na}:
            continue
        swapped = (nh == fx["away_team"])  # ev_home correspond au away de la fixture
        return fx, swapped
    return None, None


# ---------------------------------------------------------------------------
# Gel anti-look-ahead & idempotence
# ---------------------------------------------------------------------------

def _parse_commence(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def should_write(commence: dt.datetime, captured_at: dt.datetime) -> bool:
    """On ne stocke une ligne que si elle est PRÉ-match (captured_at < coup d'envoi)."""
    return captured_at < commence


def is_frozen(existing: dict | None, now: dt.datetime) -> bool:
    """Un record dont le coup d'envoi est déjà passé est gelé (jamais réécrit)."""
    if not existing:
        return False
    return _parse_commence(existing["commence_time"]) <= now


def _key(rec: dict) -> tuple:
    return (rec["date"], rec["home_team"], rec["away_team"])


# ---------------------------------------------------------------------------
# Traitement (pur) + collecte (réseau/IO)
# ---------------------------------------------------------------------------

def process_events(events: list[dict], fixtures: list[dict], existing: list[dict],
                   now: dt.datetime, name_map: dict[str, str] | None = None,
                   horizon_hours: int | None = None):
    """Construit la liste consensus mise à jour. Aucune IO, aucun réseau (testable).

    Retourne (records, matched, unmatched, skipped) où unmatched = [(home,away,raison)].
    """
    horizon_hours = config.SNAPSHOT_HORIZON_HOURS if horizon_hours is None else horizon_hours
    by_key = {_key(r): r for r in existing}
    matched, unmatched, skipped = [], [], []

    for ev in events:
        ev_home, ev_away = ev.get("home_team"), ev.get("away_team")
        commence = _parse_commence(ev["commence_time"])

        # Horizon : seulement les coups d'envoi à <= horizon_hours dans le futur.
        delta_h = (commence - now).total_seconds() / 3600.0
        if delta_h < 0 or delta_h > horizon_hours:
            skipped.append((ev_home, ev_away, f"hors horizon ({delta_h:.1f}h)"))
            continue

        pb = per_book_h2h(ev.get("bookmakers", []), ev_home, ev_away)
        if not pb:
            unmatched.append((ev_home, ev_away, "aucun h2h exploitable"))
            continue
        (ph, pd_, pa), n_books = consensus(pb)

        fx, swapped = resolve_fixture(ev_home, ev_away, commence, fixtures, name_map)
        if fx is None:
            unmatched.append((ev_home, ev_away, "fixture non appariée"))
            continue

        if swapped:
            ph, pa = pa, ph  # réorienter vers le home/away de la fixture

        if not should_write(commence, now):
            skipped.append((ev_home, ev_away, "coup d'envoi passé (non pré-match)"))
            continue

        k = (str(fx["date"]), fx["home_team"], fx["away_team"])
        if is_frozen(by_key.get(k), now):
            skipped.append((ev_home, ev_away, "record gelé (kickoff passé)"))
            continue

        by_key[k] = {
            "date": str(fx["date"]),
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "p_home": round(ph, 6),
            "p_draw": round(pd_, 6),
            "p_away": round(pa, 6),
            "commence_time": ev["commence_time"],
            "captured_at": now.isoformat(),
            "n_books": n_books,
        }
        matched.append((fx["home_team"], fx["away_team"], (ph, pd_, pa), n_books))

    records = sorted(by_key.values(), key=lambda r: (r["date"], r["home_team"]))
    return records, matched, unmatched, skipped


def _upcoming_fixtures() -> list[dict]:
    """Fixtures CDM à venir (score NaN) sous la forme attendue par resolve_fixture."""
    df = data.load_results()
    mask = ((df["tournament"] == config.WC2026_TOURNAMENT_LABEL)
            & (df["date"] >= config.WC2026_START)
            & (df["home_score"].isna()))
    fx = df[mask]
    return [{"date": r.date, "home_team": r.home_team, "away_team": r.away_team}
            for r in fx.itertuples(index=False)]


def fetch_odds(api_key: str) -> tuple[list[dict], str | None]:
    """Une requête : toutes les cotes à venir du sport WC. Retourne (events, quota_restant)."""
    url = f"{BASE}/sports/{config.ODDS_SPORT_KEY}/odds"
    resp = requests.get(url, params={
        "apiKey": api_key, "regions": config.ODDS_REGIONS,
        "markets": config.ODDS_MARKETS, "oddsFormat": config.ODDS_FORMAT,
    }, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json(), resp.headers.get("x-requests-remaining")


def collect(dry_run: bool = False) -> dict:
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        print("ODDS_API_KEY absente du .env -> collecte impossible.")
        return {"error": "no_api_key"}

    now = dt.datetime.now(UTC)
    events, remaining = fetch_odds(key)
    print(f"[market] {len(events)} événements à venir ; quota restant (x-requests-remaining)="
          f"{remaining}")

    fixtures = _upcoming_fixtures()
    existing = []
    if CONSENSUS_FILE.exists():
        existing = json.loads(CONSENSUS_FILE.read_text(encoding="utf-8"))

    records, matched, unmatched, skipped = process_events(events, fixtures, existing, now)

    print(f"[market] {len(matched)} appariés / {len(unmatched)} non appariés "
          f"/ {len(skipped)} ignorés (horizon/gel)")
    for h, a, (ph, pd_, pa), nb in matched:
        print(f"   ✓ {h} – {a} : H={ph:.3f} D={pd_:.3f} A={pa:.3f} ({nb} books)")
    for h, a, why in unmatched:
        print(f"   ✗ {h} – {a} : {why}")

    if dry_run:
        print("[market] --dry-run : rien n'est écrit.")
        return {"matched": len(matched), "unmatched": len(unmatched),
                "skipped": len(skipped), "remaining": remaining, "records": records}

    CONSENSUS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CONSENSUS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    raw_path = RAW_DIR / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    raw_path.write_text(json.dumps({"captured_at": now.isoformat(),
                                    "remaining": remaining, "events": events},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[market] consensus -> {CONSENSUS_FILE} ({len(records)} records)")
    print(f"[market] capture brute -> {raw_path}")
    return {"matched": len(matched), "unmatched": len(unmatched),
            "skipped": len(skipped), "remaining": remaining, "records": records}


def main() -> None:
    ap = argparse.ArgumentParser(description="Collecteur de snapshots marché CDM 2026")
    ap.add_argument("--dry-run", action="store_true",
                    help="affiche ce qui serait capturé sans rien écrire")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    collect(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
