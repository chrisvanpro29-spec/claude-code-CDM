"""Source H — Sources à promesses extraordinaires (vérification renforcée, pas préjugée).

Cibles : tout profil « gratuit + illimité + prédictions ML » (ex. bzzoiro/BSD).

Traitement : EXACTEMENT la même batterie neutre que les autres — aucun verdict
assigné d'avance. La seule différence : les tests doivent avoir assez de mordant
pour qu'une source fabriquée ne puisse pas les passer. Mécanisme clé :
**cross-validation contre une source indépendante déjà vérifiée** (source A).
Accord = confiance gagnée ; désaccord = signal -> `failed`. C'est ainsi que
London Strategic Edge a été pris : ses volumes ne collaient pas au vrai MNQ.

Le verdict tombe sur preuve, dans un sens comme dans l'autre.
"""

from __future__ import annotations

import io
import os

import pandas as pd
import requests

from audit.cache import cached_json, cached_text
from audit.paths import raw_dir
from audit.schema import AuditRecord, Trust

SOURCE = "H_quarantine"
TIMEOUT = 30
# Disagreement toléré sur l'échantillon croisé avant de basculer en 'failed'.
MISMATCH_THRESHOLD = 0.10


def _load_reference_results() -> pd.DataFrame | None:
    """Charge le CSV de la source A déjà mis en cache (référence indépendante)."""
    path = raw_dir("A_international_results") / "results.csv"
    if not path.exists():
        return None
    return pd.read_csv(io.StringIO(path.read_text(encoding="utf-8")))


def _cross_validate_scores(claimed: pd.DataFrame, ref: pd.DataFrame,
                           rec: AuditRecord) -> None:
    """Compare les scores annoncés par la source douteuse au socle vérifié (source A).

    Une source fabriquée diverge ici : ses scores ne collent pas à l'historique réel.
    """
    need = {"date", "home_team", "away_team", "home_score", "away_score"}
    if not need.issubset(claimed.columns) or not need.issubset(ref.columns):
        rec.note("cross-validation impossible : schéma incompatible avec la source A.")
        return
    key = ["date", "home_team", "away_team"]
    merged = claimed.merge(ref, on=key, suffixes=("_claim", "_ref"))
    if merged.empty:
        rec.note("cross-validation : 0 match en commun avec la source A "
                 "-> impossible de confirmer, signal de méfiance.")
        rec.trust = Trust.UNVERIFIED
        return
    mism = ((merged["home_score_claim"] != merged["home_score_ref"]) |
            (merged["away_score_claim"] != merged["away_score_ref"]))
    rate = float(mism.mean())
    rec.realism = (f"{len(merged)} matchs croisés avec source A ; "
                   f"désaccord scores = {rate*100:.1f}%")
    if rate <= MISMATCH_THRESHOLD:
        rec.trust = Trust.TRUSTED
        rec.note(f"✅ accord {100*(1-rate):.1f}% avec une source indépendante vérifiée "
                 "-> confiance GAGNÉE sur preuve.")
    else:
        rec.trust = Trust.FAILED
        rec.note(f"❌ {rate*100:.1f}% de scores en désaccord avec le socle réel "
                 "(source A) -> source fabriquée/peu fiable. Verdict FAILED sur preuve.")


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="unknown",
        auth_required=False,
        rate_limit="à mesurer",
        cost_to_scale="annoncé « gratuit/illimité » -> précisément à ne PAS croire sur parole",
    )
    rec.note("Traitement neutre : même grille que les autres. Le mordant vient de la "
             "cross-validation contre la source A (indépendante, déjà vérifiée).")

    base = os.getenv("QUARANTINE_BASE_URL", "").strip()
    if not base:
        rec.note("QUARANTINE_BASE_URL absente du .env -> aucune source douteuse à sonder "
                 "dans ce run. Le mécanisme est prêt : renseigner l'URL pour activer "
                 "la cross-validation.")
        rec.trust = Trust.UNVERIFIED
        rec.freshness = "non testée (pas d'URL)"
        rec.coverage = "n/a"
        return rec

    key = os.getenv("QUARANTINE_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    rec.auth_required = bool(key)

    try:
        # On tente un endpoint de résultats historiques (le plus vérifiable).
        url = base.rstrip("/") + "/results"
        text, _, _ = cached_text(SOURCE, "results.json",
                                 lambda: requests.get(url, headers=headers,
                                                      timeout=TIMEOUT).text)
        rec.access_ok = True
        try:
            claimed = pd.read_json(io.StringIO(text))
        except ValueError:
            claimed = pd.json_normalize(pd.read_json(io.StringIO(text), typ="series"))
        rec.schema = list(claimed.columns)
        rec.completeness = f"{len(claimed)} lignes annoncées"
        rec.freshness = "déclarée par la source (à confirmer par cross-validation)"

        ref = _load_reference_results()
        if ref is None:
            rec.note("source A non encore en cache -> lancer le probe A avant H "
                     "pour activer la cross-validation. Verdict provisoire : unverified.")
            rec.trust = Trust.UNVERIFIED
        else:
            _cross_validate_scores(claimed, ref, rec)

    except Exception as e:  # noqa: BLE001
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
        rec.note("Accès échoué : promesse non vérifiable dans ce run (ni confirmée, ni infirmée).")
    return rec
