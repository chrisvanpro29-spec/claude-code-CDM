"""Source G — the-odds-api (le juge, calibration).

Cotes marché (h2h, totals). **Pas pour parier** : pour juger la calibration d'un
futur modèle. Clé gratuite via .env (ODDS_API_KEY), quota mensuel limité.

Audit : le tier gratuit renvoie-t-il les marchés foot/CDM ?, quota mensuel exact,
bookmakers couverts, fraîcheur.
"""

from __future__ import annotations

import os

import requests

from audit.cache import cached_json
from audit.schema import AuditRecord, Trust

SOURCE = "G_the_odds_api"
BASE = "https://api.the-odds-api.com/v4"
TIMEOUT = 30


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="odds",
        auth_required=True,
        rate_limit="quota mensuel (tier gratuit ~500 req/mois)",
        cost_to_scale="gratuit plafonné au quota mensuel ; au-delà = paliers payants",
    )
    rec.note("Usage : calibration uniquement (juge), pas de logique de paris.")
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        rec.note("ODDS_API_KEY absente du .env -> probe non exécutable.")
        rec.trust = Trust.UNVERIFIED
        rec.freshness = "non testée (pas de clé)"
        return rec

    try:
        # 1) Lister les sports pour confirmer la présence du foot.
        r_sports = requests.get(f"{BASE}/sports", params={"apiKey": key}, timeout=TIMEOUT)
        r_sports.raise_for_status()
        sports = r_sports.json()
        rec.access_ok = True
        cached_json(SOURCE, "sports.json", lambda: sports)

        # Quota via headers.
        remaining = r_sports.headers.get("x-requests-remaining")
        used = r_sports.headers.get("x-requests-used")
        if remaining is not None:
            rec.rate_limit = f"quota mensuel ; restant={remaining}, utilisés={used}"

        soccer = [s for s in sports if str(s.get("group", "")).lower() == "soccer"
                  or "soccer" in str(s.get("key", ""))]
        wc = [s for s in sports if "world_cup" in str(s.get("key", "")).lower()
              or "world cup" in str(s.get("title", "")).lower()]
        rec.coverage = f"{len(soccer)} compétitions foot ; CDM détectée : {bool(wc)}"
        rec.note(f"clés CDM trouvées : {[s.get('key') for s in wc] or 'aucune (hors saison ?)'}")

        # 2) Tirer les cotes d'une compétition foot active (h2h, totals).
        sport_key = (wc[0]["key"] if wc else (soccer[0]["key"] if soccer else None))
        if sport_key:
            r_odds = requests.get(
                f"{BASE}/sports/{sport_key}/odds",
                params={"apiKey": key, "regions": "eu", "markets": "h2h,totals",
                        "oddsFormat": "decimal"},
                timeout=TIMEOUT,
            )
            r_odds.raise_for_status()
            odds = r_odds.json()
            cached_json(SOURCE, "odds_sample.json", lambda: odds)
            books = set()
            for ev in odds:
                for b in ev.get("bookmakers", []):
                    books.add(b.get("title"))
            markets = set()
            for ev in odds:
                for b in ev.get("bookmakers", []):
                    for m in b.get("markets", []):
                        markets.add(m.get("key"))
            rec.schema = ["sport_key", "commence_time", "home_team", "away_team",
                          "bookmakers[].title", "markets[].key", "outcomes[].price"]
            rec.completeness = f"{len(odds)} événements cotés"
            rec.realism = (f"marchés présents={sorted(markets)} ; "
                           f"{len(books)} bookmakers")
            rec.note(f"bookmakers couverts (échantillon) : {sorted(books)[:10]}")
            rec.freshness = "cotes temps réel pour les événements à venir cotés"
            rec.trust = Trust.CONDITIONAL if odds else Trust.CONDITIONAL
            rec.note("conditional : marchés foot exploitables comme juge, "
                     "sous contrainte de quota mensuel.")
        else:
            rec.freshness = "aucune compétition foot active à coter"
            rec.realism = "liste sports OK mais pas de marché foot actif au moment du run"
            rec.trust = Trust.CONDITIONAL

    except requests.HTTPError as e:
        rec.fail(e)
        code = e.response.status_code if e.response is not None else "?"
        if code == 401:
            rec.note("clé refusée (401).")
        elif code == 429:
            rec.note("quota épuisé (429).")
        rec.trust = Trust.UNVERIFIED
    except Exception as e:  # noqa: BLE001
        rec.fail(e)
    return rec
