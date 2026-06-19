# wc2026-recon — Reconnaissance des sources de données (Coupe du Monde 2026)

Outil d'**audit forensic neutre** des sources de données candidates, *avant* tout
modèle. Il interroge chaque source avec un échantillon minimal et produit un
**rapport d'audit** qui dit, pour chacune : ce qu'on peut obtenir, à quelle
granularité, à quelle fraîcheur, avec quelle fiabilité et à quel coût de montée
en charge.

> **Hors périmètre (interdit ici) :** Elo, modèle de buts, simulation,
> probabilités, logique de paris. On ne modélise rien — on regarde la matière
> première.

## Principe

Aucune source n'est étiquetée avant examen. Le champ `trust`
(`trusted` / `conditional` / `unverified` / `failed`) est un **résultat calculé
par les tests**, jamais un préjugé d'entrée. La charge de la preuve est sur la
donnée : une source n'est `trusted` qu'*après* avoir passé les tests. Les sources
à promesses extraordinaires (gratuit + illimité + ML) subissent exactement la
même batterie, plus une **cross-validation contre une source indépendante déjà
vérifiée** (source A).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # renseigner les clés API (optionnel mais recommandé)
```

## Utilisation

```bash
python recon.py
```

Le run est **idempotent** : les réponses brutes sont mises en cache dans
`data/raw/<source>/`, donc relancer ne re-télécharge pas. Chaque probe est isolé
(`try/except`) : l'échec d'une source n'interrompt jamais le run, l'erreur est
consignée dans son `AuditRecord`.

## Sorties

| Fichier | Contenu |
|---|---|
| `data/audit_report.md` | Rapport lisible : tableau de synthèse (granularité × fiabilité × effort) + une section détaillée par source. |
| `data/audit_summary.json` | Les `AuditRecord` sérialisés, réexploitables par script. |
| `data/raw/<source>/` | Échantillons bruts mis en cache, pour inspection manuelle. |

## Sources sondées

| Code | Source | Couche | Clé requise |
|---|---|---|---|
| A | `martj42/international_results` (CSV) | équipe (match) | non |
| B | Elo `eloratings.net` (recalculable depuis A) | équipe | non |
| C | football-data.org REST v4 (live CDM) | équipe (match) | `FOOTBALL_DATA_API_KEY` |
| D | StatsBomb Open Data (`statsbombpy`) | joueur (event) | non |
| E | FBref / Understat (`soccerdata`) | joueur (xG club) | non |
| F | Transfermarkt (scraping) | joueur (valeur marché) | non |
| G | the-odds-api (juge / calibration) | cotes | `ODDS_API_KEY` |
| H | Quarantaine (promesses extraordinaires) | variable | `QUARANTINE_BASE_URL` |

## Sécurité

- Clés API **uniquement** dans `.env` (jamais en dur). Voir `.env.example`.
- `.gitignore` exclut `.env` et `data/` : aucun secret ni échantillon n'est commité.

## Critère de fin

Après `python recon.py`, `audit_report.md` permet de répondre sans ambiguïté,
pour chaque couche (équipe / joueur / cotes-juge) : **quelles sources sont
fiables, à quelle granularité, et où sont les trous** — donc décider ce qui est
quantifiable avant d'écrire la première ligne de modèle.
