"""Source F — Transfermarkt (couche joueur, proxy qualité).

Valeur marché, âge, poste, minutes — proxy de qualité d'effectif. Accès par
scraping (fragile, soumis aux ToS).

Audit : récupérer l'effectif d'1 sélection avec valeurs marché ; noter la
fragilité et la conformité ToS.
"""

from __future__ import annotations

import re

import requests

from audit.cache import cached_text, save_sample
from audit.schema import AuditRecord, Trust

SOURCE = "F_transfermarkt"
# Effectif d'une sélection (exemple : France). Scraping HTML.
SQUAD_URL = "https://www.transfermarkt.com/equipe-de-france/startseite/verein/3377"
TIMEOUT = 30
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "fr,en;q=0.8",
}


def _download(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="player",
        auth_required=False,
        rate_limit="non documenté ; anti-bot agressif",
        cost_to_scale="scraping fragile, soumis aux ToS ; ne pas industrialiser sans accord",
    )
    rec.note("⚠️ Conformité ToS : Transfermarkt interdit le scraping massif. "
             "Usage reconnaissance/échantillon uniquement ici.")
    try:
        html, path, from_cache = cached_text(SOURCE, "squad.html",
                                             lambda: _download(SQUAD_URL))
        rec.access_ok = True
        rec.note(f"page effectif récupérée {'(cache)' if from_cache else ''} -> {path}")

        # Extraction best-effort des valeurs marché (€) et noms.
        values = re.findall(r"[€]\s?\d+[\.,]?\d*\s?(?:m|k|mio|M|K)", html)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            names = [a.get("title") for a in soup.select("td.hauptlink a") if a.get("title")]
            names = [n for n in names if n][:30]
        except Exception:  # noqa: BLE001
            names = []
        save_sample(SOURCE, "squad_preview.txt",
                    "Valeurs détectées:\n" + "\n".join(values[:30]) +
                    "\n\nNoms détectés:\n" + "\n".join(names))

        rec.schema = ["player_name", "market_value", "age?", "position?", "minutes?"]
        rec.completeness = (f"{len(values)} valeurs marché détectées dans la page ; "
                            f"{len(names)} noms")
        rec.realism = ("page parsée ; structure HTML dépendante du DOM Transfermarkt "
                       "(casse au moindre changement de template)")
        rec.freshness = "valeurs marché courantes (mises à jour par TM en continu)"
        rec.coverage = "1 sélection testée ; extensible aux 48 mais au prix d'un scraping fragile"

        if values:
            rec.trust = Trust.CONDITIONAL
            rec.note("conditional : données obtenues mais via scraping fragile + ToS.")
        else:
            rec.trust = Trust.CONDITIONAL
            rec.note("conditional : page récupérée mais extraction des valeurs incertaine "
                     "(DOM probablement changé / anti-bot).")

    except Exception as e:  # noqa: BLE001
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
        rec.note("Accès bloqué (anti-bot/réseau). Fragilité confirmée.")
    return rec
