"""Rend le rapport lisible (audit_report.md) et le JSON réexploitable (audit_summary.json).

Le rapport contient une section par source + un tableau de synthèse classant les
sources par (granularité × fiabilité × effort), pensé pour faire ressortir
l'asymétrie attendue : donnée équipe abondante/propre vs donnée joueur rare/fragmentée.
"""

from __future__ import annotations

import datetime as dt
import json

from .paths import REPORT_MD, SUMMARY_JSON, ensure_data_dirs
from .schema import AuditRecord, Trust

# Rangs pour le tri du tableau de synthèse (plus petit = plus haut).
_TRUST_RANK = {Trust.TRUSTED: 0, Trust.CONDITIONAL: 1, Trust.UNVERIFIED: 2, Trust.FAILED: 3}
_GRAN_RANK = {"event": 0, "player": 1, "match": 2, "team": 3, "odds": 4, "unknown": 5}

# Couche métier (lisibilité du tableau).
_LAYER = {
    "team": "équipe",
    "match": "équipe",
    "player": "joueur",
    "event": "joueur",
    "odds": "cotes-juge",
    "unknown": "?",
}

_TRUST_EMOJI = {
    Trust.TRUSTED: "✅ trusted",
    Trust.CONDITIONAL: "🟡 conditional",
    Trust.UNVERIFIED: "⬜ unverified",
    Trust.FAILED: "❌ failed",
}


def _effort(rec: AuditRecord) -> str:
    """Estimation grossière de l'effort de montée en charge, dérivée des signaux."""
    blob = " ".join(rec.notes + [rec.cost_to_scale, rec.rate_limit]).lower()
    if "scrap" in blob or "tos" in blob or "fragil" in blob:
        return "élevé (scraping/ToS)"
    if rec.auth_required and ("quota" in blob or "req/min" in rec.rate_limit.lower()):
        return "moyen (clé + rate-limit)"
    if rec.auth_required:
        return "moyen (clé requise)"
    if "rate" in blob or "pause" in blob or "sleep" in blob:
        return "moyen (pauses imposées)"
    return "faible"


def _sort_key(rec: AuditRecord):
    return (_TRUST_RANK.get(rec.trust, 9), _GRAN_RANK.get(rec.granularity, 9), rec.source)


def render_markdown(records: list[AuditRecord]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append("# Rapport d'audit — Sources de données (Coupe du Monde 2026)")
    lines.append("")
    lines.append(f"_Généré le {now} par `recon.py`. Audit forensic neutre : aucune source "
                 "n'est étiquetée avant examen ; le champ `trust` est un résultat calculé "
                 "par les tests._")
    lines.append("")
    lines.append("> Périmètre : **reconnaissance uniquement**. Aucun Elo, aucun modèle de "
                 "buts, aucune probabilité, aucune logique de paris. On regarde la matière "
                 "première.")
    lines.append("")

    # --- Tableau de synthèse -------------------------------------------------
    lines.append("## Tableau de synthèse")
    lines.append("")
    lines.append("Classé par fiabilité puis granularité. La colonne *couche* fait "
                 "ressortir l'asymétrie attendue (équipe vs joueur).")
    lines.append("")
    lines.append("| Source | Couche | Granularité | Fiabilité | Accès | Fraîcheur (live ?) "
                 "| Effort de montée en charge |")
    lines.append("|---|---|---|---|---|---|---|")
    for rec in sorted(records, key=_sort_key):
        access = "oui" if rec.access_ok else "non"
        layer = _LAYER.get(rec.granularity, "?")
        trust = _TRUST_EMOJI.get(rec.trust, rec.trust)
        fresh = rec.freshness.replace("\n", " ")
        lines.append(
            f"| {rec.source} | {layer} | {rec.granularity} | {trust} | {access} | "
            f"{fresh} | {_effort(rec)} |"
        )
    lines.append("")

    # --- Lecture par couche --------------------------------------------------
    lines.append("### Lecture par couche")
    lines.append("")
    by_layer: dict[str, list[AuditRecord]] = {}
    for rec in records:
        by_layer.setdefault(_LAYER.get(rec.granularity, "?"), []).append(rec)
    for layer in ("équipe", "joueur", "cotes-juge", "?"):
        recs = by_layer.get(layer)
        if not recs:
            continue
        usable = [r for r in recs if r.trust in (Trust.TRUSTED, Trust.CONDITIONAL)]
        names = ", ".join(sorted(r.source for r in usable)) or "aucune source exploitable"
        lines.append(f"- **{layer}** : {names}.")
    lines.append("")

    # --- Détail par source ---------------------------------------------------
    lines.append("## Détail par source")
    lines.append("")
    for rec in records:
        lines.append(f"### {rec.source}")
        lines.append("")
        lines.append(f"- **Fiabilité (`trust`)** : {_TRUST_EMOJI.get(rec.trust, rec.trust)}")
        lines.append(f"- **Accès** : {'OK' if rec.access_ok else 'ÉCHEC'} · "
                     f"auth requise : {'oui' if rec.auth_required else 'non'}")
        lines.append(f"- **Granularité** : {rec.granularity} ({_LAYER.get(rec.granularity, '?')})")
        lines.append(f"- **Rate-limit** : {rec.rate_limit}")
        lines.append(f"- **Fraîcheur** : {rec.freshness}")
        lines.append(f"- **Complétude** : {rec.completeness}")
        lines.append(f"- **Réalisme** : {rec.realism}")
        lines.append(f"- **Couverture** : {rec.coverage}")
        lines.append(f"- **Coût de montée en charge** : {rec.cost_to_scale}")
        if rec.schema:
            shown = ", ".join(rec.schema[:30])
            more = "…" if len(rec.schema) > 30 else ""
            lines.append(f"- **Schéma** ({len(rec.schema)} champs) : {shown}{more}")
        if rec.notes:
            lines.append("- **Notes** :")
            for n in rec.notes:
                lines.append(f"  - {n}")
        if rec.error:
            lines.append(f"- **Erreur** : `{rec.error}`")
        lines.append("")

    return "\n".join(lines)


def write_outputs(records: list[AuditRecord]) -> None:
    """Écrit audit_report.md et audit_summary.json."""
    ensure_data_dirs()
    REPORT_MD.write_text(render_markdown(records), encoding="utf-8")
    summary = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_sources": len(records),
        "records": [r.to_dict() for r in records],
    }
    SUMMARY_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
