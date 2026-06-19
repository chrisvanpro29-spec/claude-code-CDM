# Rapport d'audit — Sources de données (Coupe du Monde 2026)

_Généré le 2026-06-19 14:45 par `recon.py`. Audit forensic neutre : aucune source n'est étiquetée avant examen ; le champ `trust` est un résultat calculé par les tests._

> Périmètre : **reconnaissance uniquement**. Aucun Elo, aucun modèle de buts, aucune probabilité, aucune logique de paris. On regarde la matière première.

## Tableau de synthèse

Classé par fiabilité puis granularité. La colonne *couche* fait ressortir l'asymétrie attendue (équipe vs joueur).

| Source | Couche | Granularité | Fiabilité | Accès | Fraîcheur (live ?) | Effort de montée en charge |
|---|---|---|---|---|---|---|
| A_international_results | équipe | match | ✅ trusted | oui | matchs du 1872-11-30 au 2026-06-27 — inclut 192 match(s) de juin 2026 | faible |
| D_statsbomb_open | joueur | event | 🟡 conditional | oui | CDM 2026 live ABSENTE (conforme : données historiques) | faible |
| B_elo_ratings | équipe | team | 🟡 conditional | oui | snapshot courant de l'export (date exacte à confirmer côté site) | moyen (pauses imposées) |
| E_fbref_understat | joueur | player | ⬜ unverified | non | unknown | élevé (scraping/ToS) |
| F_transfermarkt | joueur | player | ⬜ unverified | non | unknown | élevé (scraping/ToS) |
| C_football_data_org | équipe | match | ⬜ unverified | non | non testée (pas de clé) | moyen (clé + rate-limit) |
| G_the_odds_api | cotes-juge | odds | ⬜ unverified | non | non testée (pas de clé) | moyen (clé + rate-limit) |
| H_quarantine | ? | unknown | ⬜ unverified | non | non testée (pas d'URL) | faible |

### Lecture par couche

- **équipe** : A_international_results, B_elo_ratings.
- **joueur** : D_statsbomb_open.
- **cotes-juge** : aucune source exploitable.
- **?** : aucune source exploitable.

## Détail par source

### A_international_results

- **Fiabilité (`trust`)** : ✅ trusted
- **Accès** : OK · auth requise : non
- **Granularité** : match (équipe)
- **Rate-limit** : aucun (fichiers raw GitHub)
- **Fraîcheur** : matchs du 1872-11-30 au 2026-06-27 — inclut 192 match(s) de juin 2026
- **Complétude** : date=0.0%; home_team=0.0%; away_team=0.0%; home_score=0.09%; away_score=0.09%
- **Réalisme** : 49477 lignes; 2 doublons (date+équipes); score max=31; scores impossibles(<0 ou >40)=0; outliers réels notables(>20)=9
- **Couverture** : 336 sélections distinctes (largement > 48 ; socle équipe complet)
- **Coût de montée en charge** : gratuit, illimité ; CSV léger à charger en entier
- **Schéma** (9 champs) : date, home_team, away_team, home_score, away_score, tournament, city, country, neutral
- **Notes** :
  - results.csv (cache) -> /home/user/claude-code-CDM/wc2026-recon/data/raw/A_international_results/results.csv
  - 9 score(s) très élevé(s) (>20) — plausibles (ex. 31-0 Australie–Samoa 2001), signalés pour vérification
  - drapeau 'neutral' présent (100% rempli)
  - ⚠️ 192 match(s) datés de juin 2026 déjà présents dans le CSV
  - goalscorers.csv (cache) : 47690 lignes, colonnes=['date', 'home_team', 'away_team', 'team', 'scorer', 'minute', 'own_goal', 'penalty']
  - shootouts.csv (cache) : 678 lignes, colonnes=['date', 'home_team', 'away_team', 'winner', 'first_shooter']
  - socle équipe propre, vérifiable, sans clé -> trusted

### B_elo_ratings

- **Fiabilité (`trust`)** : 🟡 conditional
- **Accès** : OK · auth requise : non
- **Granularité** : team (équipe)
- **Rate-limit** : non documenté (export statique)
- **Fraîcheur** : snapshot courant de l'export (date exacte à confirmer côté site)
- **Complétude** : unknown
- **Réalisme** : 244 ratings parsés ; plages à valider après mapping noms
- **Couverture** : 244 entrées (à mapper sur les 48 équipes du Mondial)
- **Coût de montée en charge** : gratuit ; OU recalcul interne depuis source A (dépendance non bloquante)
- **Schéma** (31 champs) : col_0, col_1, col_2, col_3, col_4, col_5, col_6, col_7, col_8, col_9, col_10, col_11, col_12, col_13, col_14, col_15, col_16, col_17, col_18, col_19, col_20, col_21, col_22, col_23, col_24, col_25, col_26, col_27, col_28, col_29…
- **Notes** :
  - Résilience : l'Elo est recalculable à partir du CSV de la source A (résultats historiques). L'accès externe n'est donc pas bloquant.
  - export récupéré depuis https://www.eloratings.net/World.tsv (cache) -> /home/user/claude-code-CDM/wc2026-recon/data/raw/B_elo_ratings/World.tsv
  - 244 lignes parsées (séparateur '	')
  - conditional : parsing OK mais mapping noms->codes pays à faire avant usage.

### C_football_data_org

- **Fiabilité (`trust`)** : ⬜ unverified
- **Accès** : ÉCHEC · auth requise : oui
- **Granularité** : match (équipe)
- **Rate-limit** : 10 req/min (tier gratuit, annoncé)
- **Fraîcheur** : non testée (pas de clé)
- **Complétude** : unknown
- **Réalisme** : unknown
- **Couverture** : unknown
- **Coût de montée en charge** : gratuit plafonné à 10 req/min ; point de rupture = paliers payants
- **Notes** :
  - FOOTBALL_DATA_API_KEY absente du .env -> probe non exécutable.

### D_statsbomb_open

- **Fiabilité (`trust`)** : 🟡 conditional
- **Accès** : OK · auth requise : non
- **Granularité** : event (joueur)
- **Rate-limit** : aucun (données ouvertes statiques)
- **Fraîcheur** : CDM 2026 live ABSENTE (conforme : données historiques)
- **Complétude** : xG renseigné sur les tirs
- **Réalisme** : 3245 events sur 1 match ; tirs=30 ; xG=présent ; coordonnées=présentes
- **Couverture** : 11 saison(s) de Coupe du Monde ouvertes ; couverture joueur historique, pas live 2026
- **Coût de montée en charge** : gratuit ; périmètre figé (compétitions ouvertes seulement)
- **Schéma** (89 champs) : 50_50, ball_receipt_outcome, ball_recovery_offensive, ball_recovery_recovery_failure, carry_end_location, clearance_aerial_won, clearance_body_part, clearance_head, clearance_left_foot, clearance_right_foot, counterpress, dribble_nutmeg, dribble_outcome, dribble_overrun, duel_outcome, duel_type, duration, foul_committed_advantage, foul_committed_offensive, foul_committed_penalty, foul_committed_type, foul_won_advantage, foul_won_defensive, goalkeeper_body_part, goalkeeper_end_location, goalkeeper_outcome, goalkeeper_position, goalkeeper_technique, goalkeeper_type, id…
- **Notes** :
  - 80 entrées compétition/saison ouvertes
  - CDM 2026 live ABSENTE (conforme : données historiques)
  - match inspecté : compétition 1470/274, match 3888787
  - données 360 indisponibles pour ce match : HTTPError
  - conditional : qualité event-level excellente MAIS historique — inutilisable pour la CDM 2026 live ; sert de référence xG.

### E_fbref_understat

- **Fiabilité (`trust`)** : ⬜ unverified
- **Accès** : ÉCHEC · auth requise : non
- **Granularité** : player (joueur)
- **Rate-limit** : FBref : pauses obligatoires entre pages (rate-limit durci)
- **Fraîcheur** : unknown
- **Complétude** : unknown
- **Réalisme** : unknown
- **Couverture** : unknown
- **Coût de montée en charge** : gratuit mais lent ; passage à l'échelle limité par les pauses anti-scraping
- **Notes** :
  - Trou de couverture clé : xG joueur au niveau CLUB seulement. Understat ne couvre PAS l'international ; FBref n'a pas d'xG fiable sur tous les matchs de sélection -> mapping club->sélection nécessaire, avec barres d'erreur larges.
  - Accès FBref/Understat échoué (réseau ou rate-limit). Couche joueur reste fragile par construction.
- **Erreur** : `Exception: Chrome not found! Install it first!`

### F_transfermarkt

- **Fiabilité (`trust`)** : ⬜ unverified
- **Accès** : ÉCHEC · auth requise : non
- **Granularité** : player (joueur)
- **Rate-limit** : non documenté ; anti-bot agressif
- **Fraîcheur** : unknown
- **Complétude** : unknown
- **Réalisme** : unknown
- **Couverture** : unknown
- **Coût de montée en charge** : scraping fragile, soumis aux ToS ; ne pas industrialiser sans accord
- **Notes** :
  - ⚠️ Conformité ToS : Transfermarkt interdit le scraping massif. Usage reconnaissance/échantillon uniquement ici.
  - Accès bloqué (anti-bot/réseau). Fragilité confirmée.
- **Erreur** : `HTTPError: 403 Client Error: Forbidden for url: https://www.transfermarkt.com/equipe-de-france/startseite/verein/3377`

### G_the_odds_api

- **Fiabilité (`trust`)** : ⬜ unverified
- **Accès** : ÉCHEC · auth requise : oui
- **Granularité** : odds (cotes-juge)
- **Rate-limit** : quota mensuel (tier gratuit ~500 req/mois)
- **Fraîcheur** : non testée (pas de clé)
- **Complétude** : unknown
- **Réalisme** : unknown
- **Couverture** : unknown
- **Coût de montée en charge** : gratuit plafonné au quota mensuel ; au-delà = paliers payants
- **Notes** :
  - Usage : calibration uniquement (juge), pas de logique de paris.
  - ODDS_API_KEY absente du .env -> probe non exécutable.

### H_quarantine

- **Fiabilité (`trust`)** : ⬜ unverified
- **Accès** : ÉCHEC · auth requise : non
- **Granularité** : unknown (?)
- **Rate-limit** : à mesurer
- **Fraîcheur** : non testée (pas d'URL)
- **Complétude** : unknown
- **Réalisme** : unknown
- **Couverture** : n/a
- **Coût de montée en charge** : annoncé « gratuit/illimité » -> précisément à ne PAS croire sur parole
- **Notes** :
  - Traitement neutre : même grille que les autres. Le mordant vient de la cross-validation contre la source A (indépendante, déjà vérifiée).
  - QUARANTINE_BASE_URL absente du .env -> aucune source douteuse à sonder dans ce run. Le mécanisme est prêt : renseigner l'URL pour activer la cross-validation.
