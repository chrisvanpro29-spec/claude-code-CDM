"""Source A — Résultats internationaux historiques (couche équipe, socle).

Miroir GitHub `martj42/international_results` (raw, sans auth) :
results.csv (~47k matchs), plus goalscorers.csv et shootouts.csv.

Audit : nb lignes, plage de dates, % scores manquants, doublons, distribution
des scores (scores absurdes ?), présence du drapeau terrain neutre, et la
question clé : les matchs de juin 2026 figurent-ils déjà dans le CSV ?
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from audit.cache import cached_text, save_sample
from audit.schema import AuditRecord, Trust

SOURCE = "A_international_results"
BASE = "https://raw.githubusercontent.com/martj42/international_results/master"
FILES = {
    "results.csv": f"{BASE}/results.csv",
    "goalscorers.csv": f"{BASE}/goalscorers.csv",
    "shootouts.csv": f"{BASE}/shootouts.csv",
}
KEY_COLS = ["date", "home_team", "away_team", "home_score", "away_score"]
TIMEOUT = 30


def _download(url: str) -> str:
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="match",
        auth_required=False,
        rate_limit="aucun (fichiers raw GitHub)",
        cost_to_scale="gratuit, illimité ; CSV léger à charger en entier",
    )
    try:
        text, path, from_cache = cached_text(SOURCE, "results.csv",
                                             lambda: _download(FILES["results.csv"]))
        rec.access_ok = True
        rec.note(f"results.csv {'(cache)' if from_cache else '(téléchargé)'} -> {path}")

        df = pd.read_csv(io.StringIO(text))
        rec.schema = list(df.columns)

        # Aperçu lisible mis en cache.
        save_sample(SOURCE, "results_head.txt", df.head(20).to_string())

        n = len(df)
        dmin, dmax = df["date"].min(), df["date"].max()
        rec.freshness = f"matchs du {dmin} au {dmax}"

        # Complétude sur les champs clés.
        present_keys = [c for c in KEY_COLS if c in df.columns]
        miss = df[present_keys].isna().mean().mul(100).round(2)
        rec.completeness = "; ".join(f"{c}={miss[c]}%" for c in present_keys)

        # Doublons de match (même date + mêmes équipes).
        dup = 0
        if {"date", "home_team", "away_team"}.issubset(df.columns):
            dup = int(df.duplicated(subset=["date", "home_team", "away_team"]).sum())

        # Distribution des scores + détection de scores absurdes.
        realism_bits = [f"{n} lignes", f"{dup} doublons (date+équipes)"]
        impossible = 0
        if {"home_score", "away_score"}.issubset(df.columns):
            hs, as_ = pd.to_numeric(df["home_score"], errors="coerce"), \
                      pd.to_numeric(df["away_score"], errors="coerce")
            max_goals = int(pd.concat([hs, as_]).max())
            # Vraiment impossible (corruption) : négatif ou > 40. Le record réel
            # connu est 31-0 (Australie–Samoa américaines, 2001) -> à NE PAS
            # traiter comme une corruption.
            impossible = int(((hs < 0) | (as_ < 0) | (hs > 40) | (as_ > 40)).sum())
            # Outliers réels mais notables (à signaler sans condamner la source).
            outliers = int(((hs > 20) | (as_ > 20)).sum())
            realism_bits.append(f"score max={max_goals}")
            realism_bits.append(f"scores impossibles(<0 ou >40)={impossible}")
            realism_bits.append(f"outliers réels notables(>20)={outliers}")
            if impossible > 0:
                rec.note(f"{impossible} score(s) impossible(s) -> corruption probable, à inspecter")
            if outliers > 0:
                rec.note(f"{outliers} score(s) très élevé(s) (>20) — plausibles "
                         "(ex. 31-0 Australie–Samoa 2001), signalés pour vérification")
        rec.realism = "; ".join(realism_bits)

        # Drapeau terrain neutre.
        if "neutral" in df.columns:
            rec.note(f"drapeau 'neutral' présent ({df['neutral'].notna().mean()*100:.0f}% rempli)")
        else:
            rec.note("drapeau 'neutral' ABSENT")

        # Couverture (nb d'équipes distinctes).
        teams = set()
        if "home_team" in df.columns:
            teams |= set(df["home_team"].dropna().unique())
        if "away_team" in df.columns:
            teams |= set(df["away_team"].dropna().unique())
        rec.coverage = (f"{len(teams)} sélections distinctes (largement > 48 ; "
                        "socle équipe complet)")

        # Question clé : juin 2026 déjà présent ?
        dates = pd.to_datetime(df["date"], errors="coerce")
        jun2026 = int(((dates >= "2026-06-01") & (dates <= "2026-06-30")).sum())
        if jun2026 > 0:
            rec.note(f"⚠️ {jun2026} match(s) datés de juin 2026 déjà présents dans le CSV")
            rec.freshness += f" — inclut {jun2026} match(s) de juin 2026"
        else:
            rec.note("aucun match de juin 2026 (la CDM live n'y est pas encore)")
            rec.freshness += " — pas de match de juin 2026 (CDM live absente)"

        # Fichiers compagnons.
        for fname in ("goalscorers.csv", "shootouts.csv"):
            try:
                ctext, _, fc = cached_text(SOURCE, fname, lambda u=FILES[fname]: _download(u))
                cdf = pd.read_csv(io.StringIO(ctext))
                rec.note(f"{fname} {'(cache)' if fc else '(téléchargé)'} : "
                         f"{len(cdf)} lignes, colonnes={list(cdf.columns)}")
            except Exception as e:  # noqa: BLE001
                rec.note(f"{fname} indisponible : {type(e).__name__}: {e}")

        # Verdict : socle propre, vérifiable, sans clé. Seul un score IMPOSSIBLE
        # (corruption) fait basculer en conditional ; les outliers réels ne
        # condamnent pas la source.
        if impossible > 0:
            rec.trust = Trust.CONDITIONAL
            rec.note("score(s) impossible(s) détecté(s) -> conditional jusqu'à nettoyage")
        else:
            rec.trust = Trust.TRUSTED
            rec.note("socle équipe propre, vérifiable, sans clé -> trusted")

    except Exception as e:  # noqa: BLE001
        rec.fail(e)
    return rec
