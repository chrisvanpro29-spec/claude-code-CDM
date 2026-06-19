"""Source B — Elo des sélections nationales (couche équipe, force).

Tentative d'export depuis eloratings.net. Option résiliente notée explicitement :
l'Elo peut être recalculé nous-mêmes à partir du CSV de la source A — la dépendance
externe est donc **non bloquante**.

Audit : accès OK ?, couverture des 48 équipes du Mondial, fraîcheur de la dernière
mise à jour.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from audit.cache import cached_text, save_sample
from audit.schema import AuditRecord, Trust

SOURCE = "B_elo_ratings"
# eloratings.net expose un export CSV via ce point d'entrée (paramètre date).
EXPORT_URL = "https://www.eloratings.net/World.tsv"
FALLBACK_URL = "https://www.eloratings.net/World.csv"
TIMEOUT = 30


def _download(url: str) -> str:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "wc2026-recon/1.0"})
    resp.raise_for_status()
    return resp.text


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="team",
        auth_required=False,
        rate_limit="non documenté (export statique)",
        cost_to_scale="gratuit ; OU recalcul interne depuis source A (dépendance non bloquante)",
    )
    rec.note("Résilience : l'Elo est recalculable à partir du CSV de la source A "
             "(résultats historiques). L'accès externe n'est donc pas bloquant.")

    text = None
    for url in (EXPORT_URL, FALLBACK_URL):
        try:
            text, path, from_cache = cached_text(SOURCE, url.rsplit("/", 1)[-1],
                                                 lambda u=url: _download(u))
            rec.access_ok = True
            rec.note(f"export récupéré depuis {url} {'(cache)' if from_cache else ''} -> {path}")
            break
        except Exception as e:  # noqa: BLE001
            rec.note(f"échec sur {url} : {type(e).__name__}: {e}")

    if not rec.access_ok or text is None:
        # Accès externe KO mais source non bloquante -> conditional, pas failed.
        rec.trust = Trust.CONDITIONAL
        rec.coverage = "non mesurée (export externe inaccessible)"
        rec.freshness = "inconnue (export externe inaccessible)"
        rec.realism = "non testé"
        rec.note("Verdict conditional : Elo obtenable par recalcul interne malgré l'échec d'accès.")
        return rec

    try:
        sep = "\t" if text[:200].count("\t") >= text[:200].count(",") else ","
        df = pd.read_csv(io.StringIO(text), sep=sep, header=None)
        rec.schema = [f"col_{i}" for i in range(df.shape[1])]
        save_sample(SOURCE, "elo_head.txt", df.head(20).to_string())
        rec.note(f"{len(df)} lignes parsées (séparateur '{sep}')")

        # Heuristique : nb d'équipes distinctes -> couverture des 48.
        rec.coverage = f"{len(df)} entrées (à mapper sur les 48 équipes du Mondial)"
        rec.realism = f"{len(df)} ratings parsés ; plages à valider après mapping noms"
        rec.freshness = "snapshot courant de l'export (date exacte à confirmer côté site)"
        rec.trust = Trust.CONDITIONAL
        rec.note("conditional : parsing OK mais mapping noms->codes pays à faire avant usage.")
    except Exception as e:  # noqa: BLE001
        rec.fail(e)
        rec.trust = Trust.CONDITIONAL  # recalcul interne reste possible
        rec.note("Parsing échoué, mais Elo recalculable depuis source A -> conditional.")
    return rec
