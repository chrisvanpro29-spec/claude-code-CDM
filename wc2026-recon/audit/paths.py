"""Chemins du projet, résolus depuis l'emplacement du package (indépendant du cwd)."""

from __future__ import annotations

from pathlib import Path

# .../wc2026-recon/audit/paths.py -> racine = .../wc2026-recon
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REPORT_MD = DATA_DIR / "audit_report.md"
SUMMARY_JSON = DATA_DIR / "audit_summary.json"


def raw_dir(source: str) -> Path:
    """Répertoire de cache brut d'une source (créé à la demande)."""
    d = RAW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_data_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
