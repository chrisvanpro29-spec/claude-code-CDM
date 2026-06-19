"""Cache disque des réponses brutes -> run idempotent, re-jouable hors-ligne.

Objectif double :
  1. respecter les rate-limits (on ne re-télécharge pas ce qu'on a déjà) ;
  2. conserver les échantillons dans data/raw/<source>/ pour inspection manuelle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .paths import raw_dir


def cached_text(source: str, name: str, fetch: Callable[[], str],
                refresh: bool = False) -> tuple[str, Path, bool]:
    """Retourne (contenu, chemin, from_cache).

    `fetch` n'est appelé que si le fichier n'existe pas (ou refresh=True).
    """
    path = raw_dir(source) / name
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8"), path, True
    content = fetch()
    path.write_text(content, encoding="utf-8")
    return content, path, False


def cached_json(source: str, name: str, fetch: Callable[[], Any],
                refresh: bool = False) -> tuple[Any, Path, bool]:
    """Idem `cached_text` mais pour du JSON (sérialisé indenté)."""
    path = raw_dir(source) / name
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8")), path, True
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data, path, False


def save_sample(source: str, name: str, content: str) -> Path:
    """Écrit un extrait d'échantillon (aperçu lisible) dans data/raw/<source>/."""
    path = raw_dir(source) / name
    path.write_text(content, encoding="utf-8")
    return path
