"""Source E — FBref / Understat via `soccerdata` (couche joueur, xG club).

Stats joueur (tirs, xG, npxG, minutes) au niveau **club**, à mapper ensuite sur
les sélections. Understat ne couvre pas l'international ; FBref a un rate-limiting
durci (pauses obligatoires entre pages).

Audit : tirer les stats de tir d'un joueur sur une saison de club, mesurer le
temps imposé par le rate-limit, documenter explicitement les trous de couverture
xG à l'international.
"""

from __future__ import annotations

import time

from audit.cache import save_sample
from audit.schema import AuditRecord, Trust

SOURCE = "E_fbref_understat"


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="player",
        auth_required=False,
        rate_limit="FBref : pauses obligatoires entre pages (rate-limit durci)",
        cost_to_scale="gratuit mais lent ; passage à l'échelle limité par les pauses anti-scraping",
    )
    rec.note("Trou de couverture clé : xG joueur au niveau CLUB seulement. "
             "Understat ne couvre PAS l'international ; FBref n'a pas d'xG fiable "
             "sur tous les matchs de sélection -> mapping club->sélection nécessaire, "
             "avec barres d'erreur larges.")
    try:
        import soccerdata as sd
    except Exception as e:  # noqa: BLE001
        rec.note("soccerdata non installé/importable.")
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
        return rec

    try:
        # Saison de club récente, grand-5 championnats.
        t0 = time.time()
        fbref = sd.FBref(leagues="ENG-Premier League", seasons="2324")
        shooting = fbref.read_player_season_stats(stat_type="shooting")
        elapsed = time.time() - t0
        rec.access_ok = True
        rec.rate_limit = f"FBref : {elapsed:.1f}s pour 1 saison/championnat (pauses incluses)"

        cols = [str(c) for c in shooting.columns.tolist()]
        rec.schema = cols
        save_sample(SOURCE, "fbref_shooting_head.txt", shooting.head(20).to_string())

        n = len(shooting)
        has_xg = any("xg" in c.lower() for c in cols)
        has_sh = any(c.lower() in ("sh", "shots") or "sh_" in c.lower() for c in cols)
        rec.completeness = f"{n} lignes joueur ; xG={'présent' if has_xg else 'absent'}"
        rec.realism = (f"stats de tir récupérées sur {n} joueurs (PL 23/24) ; "
                       f"colonnes xG={'oui' if has_xg else 'non'}, tirs={'oui' if has_sh else 'non'}")
        rec.freshness = "saisons de club (pas de live CDM 2026)"
        rec.coverage = ("joueurs de club du championnat tiré ; couverture des 48 "
                        "sélections = partielle et indirecte (via clubs)")
        rec.trust = Trust.CONDITIONAL
        rec.note("conditional : xG club exploitable mais lent + trou international "
                 "-> proxy joueur à manier avec prudence.")

    except Exception as e:  # noqa: BLE001
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
        rec.note("Accès FBref/Understat échoué (réseau ou rate-limit). "
                 "Couche joueur reste fragile par construction.")
    return rec
