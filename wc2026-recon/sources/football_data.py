"""Source C — football-data.org, REST v4 (couche équipe, live).

Endpoints : /v4/competitions/WC/matches, /standings, /scorers.
Clé gratuite via .env (FOOTBALL_DATA_API_KEY). Contraintes connues : 10 req/min,
pas de données niveau joueur sur le tier gratuit, scores potentiellement différés.

Audit : la clé gratuite renvoie-t-elle bien la CDM ?, champs réellement présents,
fraîcheur (matchs terminés scorés ?), headers de rate-limit, latence, et
confirmation de l'absence de champs joueur.
"""

from __future__ import annotations

import os
import time

import requests

from audit.cache import cached_json
from audit.schema import AuditRecord, Trust

SOURCE = "C_football_data_org"
BASE = "https://api.football-data.org/v4"
TIMEOUT = 30


def _get(endpoint: str, key: str) -> tuple[dict, dict, float]:
    url = f"{BASE}{endpoint}"
    t0 = time.time()
    resp = requests.get(url, headers={"X-Auth-Token": key}, timeout=TIMEOUT)
    latency = time.time() - t0
    resp.raise_for_status()
    return resp.json(), dict(resp.headers), latency


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="match",
        auth_required=True,
        rate_limit="10 req/min (tier gratuit, annoncé)",
        cost_to_scale="gratuit plafonné à 10 req/min ; point de rupture = paliers payants",
    )
    key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    if not key:
        rec.note("FOOTBALL_DATA_API_KEY absente du .env -> probe non exécutable.")
        rec.trust = Trust.UNVERIFIED
        rec.freshness = "non testée (pas de clé)"
        return rec

    try:
        data, headers, latency = _get("/competitions/WC/matches", key)
        rec.access_ok = True
        cached_json(SOURCE, "wc_matches.json", lambda: data)

        # Rate-limit réellement observé via les headers.
        rl = headers.get("X-Requests-Available-Minute") or headers.get("X-RequestsAvailableMinute")
        if rl is not None:
            rec.rate_limit = f"10 req/min ; restant cette minute={rl} (header observé)"
        rec.note(f"latence /matches = {latency:.2f}s")

        matches = data.get("matches", [])
        comp = data.get("competition", {})
        rec.note(f"compétition renvoyée : {comp.get('name')} ({comp.get('code')})")

        if matches:
            sample = matches[0]
            rec.schema = sorted(sample.keys())
            # Confirmer l'absence de champs joueur.
            has_player = any(k in sample for k in ("lineup", "bench", "players", "goals_detail"))
            rec.note("champs joueur (lineup/bench/players) : "
                     + ("PRÉSENTS (inattendu)" if has_player else "ABSENTS (conforme tier gratuit)"))
            # Fraîcheur : matchs terminés scorés ?
            finished = [m for m in matches if m.get("status") == "FINISHED"]
            scored = [m for m in finished
                      if (m.get("score", {}).get("fullTime", {}).get("home")) is not None]
            rec.freshness = (f"{len(matches)} matchs ; {len(finished)} terminés ; "
                             f"{len(scored)} scorés")
            rec.completeness = (f"{len(scored)}/{len(finished)} matchs terminés ont un score plein"
                                if finished else "aucun match terminé pour l'instant")
            rec.coverage = f"{len(matches)} matchs CDM exposés (couche équipe)"
            rec.realism = "structure conforme (status, score.fullTime, homeTeam/awayTeam)"
        else:
            rec.freshness = "0 match renvoyé (CDM pas encore peuplée côté API ?)"
            rec.coverage = "0 match"
            rec.realism = "vide"

        # standings + scorers (best effort, respect du rate-limit avec sleep).
        for ep, fname in (("/competitions/WC/standings", "wc_standings.json"),
                          ("/competitions/WC/scorers", "wc_scorers.json")):
            try:
                time.sleep(6.5)  # ~10 req/min -> >6s entre requêtes
                d2, _, _ = _get(ep, key)
                cached_json(SOURCE, fname, lambda d=d2: d)
                rec.note(f"{ep} accessible")
            except Exception as e:  # noqa: BLE001
                rec.note(f"{ep} : {type(e).__name__}: {e}")

        # Verdict.
        if matches:
            rec.trust = Trust.CONDITIONAL
            rec.note("conditional : live exploitable au niveau équipe, mais pas de "
                     "données joueur et scores potentiellement différés.")
        else:
            rec.trust = Trust.CONDITIONAL
            rec.note("conditional : accès OK mais compétition vide à ce stade.")

    except requests.HTTPError as e:
        rec.fail(e)
        code = e.response.status_code if e.response is not None else "?"
        if code in (401, 403):
            rec.note("clé refusée ou CDM hors périmètre du tier gratuit.")
        rec.trust = Trust.UNVERIFIED
    except Exception as e:  # noqa: BLE001
        rec.fail(e)
    return rec
