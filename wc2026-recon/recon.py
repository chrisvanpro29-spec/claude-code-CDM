#!/usr/bin/env python3
"""Orchestrateur de reconnaissance des sources — Coupe du Monde 2026.

Lance tous les probes (chacun isolé : l'échec d'un module n'interrompt jamais le
run), met en cache les échantillons bruts dans data/raw/, puis génère le rapport
data/audit_report.md et data/audit_summary.json.

Périmètre : AUDIT uniquement. Aucun Elo, aucun modèle de buts, aucune simulation,
aucune probabilité, aucune logique de paris. On regarde la matière première.

Usage :
    python recon.py
"""

from __future__ import annotations

import importlib
import traceback

from dotenv import load_dotenv

from audit.paths import REPORT_MD, SUMMARY_JSON, ensure_data_dirs
from audit.report import write_outputs
from audit.schema import AuditRecord, Trust

# Ordre important : A (socle) avant H (quarantine) pour que la cross-validation
# dispose du cache de référence.
PROBES = [
    ("sources.kaggle_results", "Source A — résultats internationaux historiques"),
    ("sources.elo", "Source B — Elo sélections nationales"),
    ("sources.football_data", "Source C — football-data.org (live)"),
    ("sources.statsbomb", "Source D — StatsBomb Open Data"),
    ("sources.fbref_understat", "Source E — FBref / Understat (xG club)"),
    ("sources.transfermarkt", "Source F — Transfermarkt (proxy qualité)"),
    ("sources.odds_api", "Source G — the-odds-api (juge / calibration)"),
    ("sources.quarantine", "Source H — sources à promesses extraordinaires"),
]


def run_probe(module_name: str, label: str) -> AuditRecord:
    """Exécute un probe en l'isolant complètement : aucune exception ne remonte."""
    print(f"  → {label} …", flush=True)
    try:
        mod = importlib.import_module(module_name)
        rec = mod.probe()
    except Exception as e:  # noqa: BLE001 — filet de sécurité ultime
        rec = AuditRecord(source=module_name, trust=Trust.UNVERIFIED)
        rec.error = f"{type(e).__name__}: {e}"
        rec.note("Probe crashé au niveau orchestrateur (capturé).")
        traceback.print_exc()
    print(f"    {rec.source}: access_ok={rec.access_ok} trust={rec.trust}"
          + (f" error={rec.error}" if rec.error else ""), flush=True)
    return rec


def main() -> None:
    load_dotenv()  # charge .env si présent (clés API)
    ensure_data_dirs()

    print("Reconnaissance des sources — Coupe du Monde 2026")
    print("=" * 56)
    records: list[AuditRecord] = []
    for module_name, label in PROBES:
        records.append(run_probe(module_name, label))

    write_outputs(records)

    print("=" * 56)
    by_trust: dict[str, int] = {}
    for r in records:
        by_trust[r.trust] = by_trust.get(r.trust, 0) + 1
    print("Synthèse fiabilité :", ", ".join(f"{k}={v}" for k, v in sorted(by_trust.items())))
    print(f"Rapport  : {REPORT_MD}")
    print(f"Résumé   : {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
