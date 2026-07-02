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

---

# Moteur de pronostics CDM 2026 (extension)

Au-dessus de l'audit, un moteur produit des probabilités **calibrées** par match
(1X2, over/under, score exact) et, par Monte Carlo, les probas de qualification /
titre. Objectif : **égaler le marché et être bien calibré**, pas parier. Le marché
(source G) est le juge.

## Principes (non négociables)

- **Traçabilité** : proba ← λ ← forces α/β (± tilt joueur) ← matchs pondérés. Pas
  de boîte noire.
- **Anti-fuite par construction** : toute donnée joueur passe par l'unique
  fonction-porte `note_joueur(joueur, date_ref)` qui filtre `matchs[date < date_ref]`
  en dur. Un test unitaire prouve qu'aucun match `>= date_ref` n'est jamais lu.
- **Gel out-of-sample** : les matchs CDM 2026 ne fittent jamais la baseline équipe ;
  ils sont le jeu de test, rejoué chronologiquement.
- **Séparabilité** : la couche joueur est un interrupteur (`PLAYER_LAYER_ON`) + un
  poids borné `w`. La validation tourne OFF puis ON sur les mêmes matchs.
- **Pré-enregistrement** : tous les hyperparamètres sont figés dans `config.py`
  AVANT de regarder le moindre Brier. Une seule passe de test.
- **Pas de note fabriquée** : là où la donnée joueur manque, la couche se désactive
  pour ce match (fallback équipe seule), et c'est signalé.

## Architecture

| Fichier | Rôle |
|---|---|
| `config.py` | TOUS les hyperparamètres pré-enregistrés |
| `engine/team_model.py` | Module 1 — Dixon-Coles (MLE pondéré time-decay, gradient analytique) |
| `engine/elo.py` | Elo recalculé depuis source A (cohérence, pas source des buts) |
| `engine/league_strength.py` | Coefficients de force des ligues (§3.3) |
| `engine/player_form.py` | Module 2 — fonction-porte `note_joueur` + agrégation (shrinkage, minutes) |
| `engine/player_data.py` | Alimentation FBref des composantes par 90 (aplatissement, /90, ajustement ligue) |
| `engine/squad_quality.py` | Qualité d'effectif dérivée des composantes FBref (SoFIFA abandonné : scraping cassé), agrégée par sélection puis centrée (4e tilt) |
| `engine/squads.py` | Ingestion des effectifs CDM 2026 (Wikipédia) : parsing, alignement noms de nations, recalage noms joueur |
| `engine/coupling.py` | Tilt borné des λ : forme + milieu + qualité, séparables (interrupteur + poids) |
| `engine/simulate.py` | Module 3 — Monte Carlo du tournoi (format réel 48 équipes) |
| `engine/market_collector.py` | Collecteur de snapshots marché (the-odds-api) — le juge qui s'accumule |
| `validation/walk_forward.py` | Module 4 — replay chronologique, le juge |
| `validation/metrics.py` | Brier, log-loss, reliability diagram |
| `tests/` | anti-fuite (`test_no_lookahead`), couplage (`test_coupling`), standardisation (`test_standardization`), centrage (`test_centering`), milieu (`test_midfield`), collecteur marché (`test_market_collector`), extraction FBref (`test_player_data`), qualité d'effectif (`test_squad_quality`), ingestion effectifs (`test_squads`) |

## Utilisation

```bash
python recon.py                       # (prérequis) met results.csv en cache
python ingest_squads.py               # ingestion ponctuelle des effectifs (Wikipédia) -> data/squads.json
python ingest_squads.py --refresh     # re-tire (ex. remplacement blessure)
python -m engine.market_collector --dry-run   # liste les lignes marché à capturer (sans écrire)
python -m engine.market_collector             # capture/maintient data/raw/market_snapshots/consensus.json
python -m validation.walk_forward     # le juge : Brier OFF vs ON (+ vs marché) + reliability + verdict
python -m pytest tests/ -q            # garanties anti-fuite, couplage, collecteur marché, ingestion effectifs
```

**Ingestion des effectifs** : ponctuelle, pas un flux récurrent — les effectifs
CDM 2026 sont figés (annoncés le 2 juin). `data/squads.json` (`{nation: [nom, ...]}`,
noms alignés sur `results.csv`) alimente à la fois `squad_quality.centered_quality`
et l'agrégation de forme par sélection (`player_form.team_notes`, via
`validation.walk_forward.load_squads`). Le recalage des noms joueur entre
Wikipédia et FBref (normalisation + correspondance exacte puis approchée)
ne devine jamais : les non-appariés sont loggés.

**Collecteur marché (chronosensible)** : capture, avant chaque match, la ligne 1X2
consensus dé-viggée et la résout contre les fixtures (jointure exacte). À lancer
régulièrement (cron, plusieurs fois les jours de match) — un match joué sans
snapshot pré-coup d'envoi est perdu (le tier gratuit ne donne pas l'historique des
cotes). Chaque match capturé devient un point de comparaison modèle-vs-marché.

Sorties dans `data/validation/` : `walk_forward_report.md`, `walk_forward.json`,
`reliability.png`.

## État dans cet environnement

- **Baseline équipe** : fit OK (convergence propre), Brier 1X2 out-of-sample
  ~0.58 sur les matchs CDM déjà joués — nettement mieux que l'uniforme (0.667).
- **Couche joueur** : machinerie complète et testée (composantes standardisées en
  z-score puis pondérées ; tilt centré sur la référence ligue ; différentiel de
  milieu branché), mais **inactive** faute de données joueur (FBref/Understat
  indisponibles ici — cf. audit). Conformément au principe « pas de note
  fabriquée », elle reste coupée et le rapport le dit. Les 23 tests prouvent la
  logique des trois molettes *avant* tout branchement de données.
- **Vs marché** : nécessite des snapshots de cotes capturés *avant* chaque match
  (the-odds-api ne renvoie pas de cotes rétroactives).
