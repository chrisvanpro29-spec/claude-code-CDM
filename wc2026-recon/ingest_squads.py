#!/usr/bin/env python3
"""Point d'entrée — ingestion des effectifs CDM 2026 (Wikipédia).

Ingestion PONCTUELLE (effectifs figés, annoncés le 2 juin) : par défaut, réutilise
data/squads.json s'il existe déjà (idempotent, ne re-scrape pas). `--refresh`
force un nouveau tirage — utile en cas de remplacement sur blessure.

Usage :
    python ingest_squads.py             # ingestion initiale (ou no-op si déjà fait)
    python ingest_squads.py --refresh   # re-tire depuis Wikipédia
"""

from __future__ import annotations

import argparse

from engine import squads


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestion des effectifs CDM 2026 (Wikipédia)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-tire depuis Wikipédia même si data/squads.json existe déjà")
    args = ap.parse_args()

    already_cached = squads.SQUADS_JSON.exists() and not args.refresh
    result = squads.ingest(refresh=args.refresh)

    expected = squads.canonical_teams()
    missing = [t for t in expected if t not in result]

    print(f"[squads] {'réutilisé (cache)' if already_cached else 'tiré depuis Wikipédia'} "
          f"-> {squads.SQUADS_JSON}")
    print(f"[squads] {len(result)}/{len(expected)} sélections ingérées, "
          f"{sum(len(v) for v in result.values())} joueurs au total")
    if missing:
        print(f"[squads] ⚠️  {len(missing)} sélection(s) introuvable(s) sur la page "
              f"(jamais devinées) : {missing}")
    sizes = {t: len(v) for t, v in result.items()}
    off_size = {t: n for t, n in sizes.items() if abs(n - squads.EXPECTED_SQUAD_SIZE) > 3}
    if off_size:
        print(f"[squads] effectifs à taille inhabituelle (attendu ~{squads.EXPECTED_SQUAD_SIZE}) : "
              f"{off_size}")


if __name__ == "__main__":
    main()
