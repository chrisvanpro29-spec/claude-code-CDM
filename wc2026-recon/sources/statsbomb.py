"""Source D — StatsBomb Open Data (couche joueur, qualité mais historique).

Via `statsbombpy`, sans auth. On liste les compétitions, on confirme que la CDM
2026 live N'EST PAS présente (attendu : absente), on tire 1 match d'une CDM passée
pour inspecter le schéma d'events (xG, coordonnées de tir), on compte les events
et on vérifie la dispo des données 360.
"""

from __future__ import annotations

from audit.cache import save_sample
from audit.schema import AuditRecord, Trust

SOURCE = "D_statsbomb_open"


def probe() -> AuditRecord:
    rec = AuditRecord(
        source=SOURCE,
        granularity="event",
        auth_required=False,
        rate_limit="aucun (données ouvertes statiques)",
        cost_to_scale="gratuit ; périmètre figé (compétitions ouvertes seulement)",
    )
    try:
        from statsbombpy import sb  # import tardif : absence = note, pas crash global
    except Exception as e:  # noqa: BLE001
        rec.note("statsbombpy non installé/importable.")
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
        return rec

    try:
        comps = sb.competitions()
        rec.access_ok = True
        rec.note(f"{len(comps)} entrées compétition/saison ouvertes")
        save_sample(SOURCE, "competitions_head.txt", comps.head(30).to_string())

        # CDM 2026 live présente ? (attendu : NON)
        names = comps.get("competition_name")
        seasons = comps.get("season_name")
        wc_2026 = False
        if names is not None and seasons is not None:
            mask = names.str.contains("World Cup", case=False, na=False) & \
                   seasons.astype(str).str.contains("2026", na=False)
            wc_2026 = bool(mask.any())
        rec.freshness = ("CDM 2026 présente (inattendu)" if wc_2026
                         else "CDM 2026 live ABSENTE (conforme : données historiques)")
        rec.note(rec.freshness)

        # Lister les World Cups disponibles.
        wc_rows = comps[names.str.contains("World Cup", case=False, na=False)] \
            if names is not None else comps.iloc[0:0]
        rec.coverage = (f"{len(wc_rows)} saison(s) de Coupe du Monde ouvertes ; "
                        "couverture joueur historique, pas live 2026")

        # Tirer 1 match d'une CDM passée et inspecter les events.
        if len(wc_rows):
            row = wc_rows.iloc[0]
            cid, sid = int(row["competition_id"]), int(row["season_id"])
            matches = sb.matches(competition_id=cid, season_id=sid)
            if len(matches):
                mid = int(matches.iloc[0]["match_id"])
                events = sb.events(match_id=mid)
                rec.schema = sorted(events.columns.tolist())
                save_sample(SOURCE, "events_sample_head.txt", events.head(20).to_string())
                has_xg = "shot_statsbomb_xg" in events.columns
                has_loc = "location" in events.columns
                shots = int((events.get("type") == "Shot").sum()) if "type" in events else 0
                rec.realism = (f"{len(events)} events sur 1 match ; tirs={shots} ; "
                               f"xG={'présent' if has_xg else 'absent'} ; "
                               f"coordonnées={'présentes' if has_loc else 'absentes'}")
                rec.completeness = ("xG renseigné sur les tirs"
                                    if has_xg else "xG manquant")
                rec.note(f"match inspecté : compétition {cid}/{sid}, match {mid}")
                # Données 360 ?
                try:
                    frames = sb.frames(match_id=mid)
                    rec.note(f"données 360 dispo pour ce match : {len(frames)} frames")
                except Exception as e:  # noqa: BLE001
                    rec.note(f"données 360 indisponibles pour ce match : {type(e).__name__}")
                rec.trust = Trust.CONDITIONAL if has_xg else Trust.CONDITIONAL
                rec.note("conditional : qualité event-level excellente MAIS historique — "
                         "inutilisable pour la CDM 2026 live ; sert de référence xG.")
            else:
                rec.note("aucun match listé pour la CDM trouvée")
                rec.trust = Trust.CONDITIONAL
        else:
            rec.note("aucune CDM trouvée dans les compétitions ouvertes")
            rec.trust = Trust.CONDITIONAL

    except Exception as e:  # noqa: BLE001
        rec.fail(e)
        rec.trust = Trust.UNVERIFIED
    return rec
