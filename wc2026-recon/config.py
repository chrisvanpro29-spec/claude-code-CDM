"""config.py — TOUS les hyperparamètres, pré-enregistrés AVANT de regarder le moindre Brier.

Règle d'or (brief §1.5) : ces valeurs sont figées ici une fois pour toutes. La
validation walk-forward ne tourne qu'UNE passe ; aucun re-tuning après avoir vu
les métriques. Modifier un seul nombre ici après avoir lu un Brier = tricher.
"""

from __future__ import annotations

import math
import datetime as dt

# ---------------------------------------------------------------------------
# Gel out-of-sample (brief §1.3) : aucune donnée >= cette date ne sert à fitter
# la baseline équipe. C'est le coup d'envoi du 1er match de la CDM 2026.
# ---------------------------------------------------------------------------
WC2026_START = dt.date(2026, 6, 11)
WC2026_TOURNAMENT_LABEL = "FIFA World Cup"

# ---------------------------------------------------------------------------
# Module 1 — Dixon-Coles
# ---------------------------------------------------------------------------
# Décroissance temporelle exp(-xi * Δt_jours). Demi-vie pré-enregistrée ~2 ans.
TIME_DECAY_HALFLIFE_DAYS = 730          # ~2 ans (ordre de grandeur figé, non optimisé)
XI = math.log(2) / TIME_DECAY_HALFLIFE_DAYS

# Fenêtre d'entraînement : on ne garde que l'historique récent (au-delà, le poids
# est négligeable). 16 ans -> poids < ~2e-3 à la borne. Borne les paramètres.
TRAIN_WINDOW_YEARS = 16

# Une équipe vue < MIN_MATCHES_PER_TEAM fois dans la fenêtre est repliée sur un
# pseudo-adversaire générique "OTHER" (évite de faire exploser le nb de paramètres
# sur des sélections quasi jamais observées).
MIN_MATCHES_PER_TEAM = 12
OTHER_TEAM = "__OTHER__"

# Bornes d'optimisation des forces (log-échelle) et init.
DC_PARAM_BOUND = 3.0                    # |α_i|, |β_i| <= 3 (garde-fou numérique)
DC_RHO_BOUNDS = (-0.2, 0.2)             # corrélation Dixon-Coles (petits scores)
DC_RHO_INIT = -0.05
DC_HOME_ADV_INIT = 0.25                 # γ initial (avantage du terrain)
DC_HOME_ADV_BOUNDS = (0.0, 0.6)
DC_INTERCEPT_INIT = 0.0                 # μ (niveau global de buts, log)
DC_INTERCEPT_BOUNDS = (-1.0, 1.0)
DC_IDENTIFIABILITY_PENALTY = 1e3        # force mean(α)=mean(β)=0
DC_MAX_GOALS = 10                       # taille matrice de scores (0..10 par équipe)
DC_OPTIMIZER_MAXITER = 1000             # budget de convergence numérique (pas un levier statistique)

# ---------------------------------------------------------------------------
# Module 2 — Couche joueur (forme/effectif)
# ---------------------------------------------------------------------------
PLAYER_LAYER_ON = True                  # interrupteur global (brief §1.4)
CLUB_FORM_WINDOW = 20                   # 20 derniers matchs de club
NATIONAL_FORM_WINDOW = 10               # 10 derniers en sélection

# Shrinkage empirical-Bayes (James-Stein) : note tirée vers la moyenne de poste.
# k = nb de matchs "équivalents" ajoutés à la moyenne. Plus k est grand, plus on
# tire fort vers la moyenne (= moins de confiance quand peu de matchs).
SHRINKAGE_K = 10

# Couverture minimale d'un effectif pour activer la couche sur un match donné
# (brief §3.6 / §1.6 : pas de note fabriquée). En-dessous -> fallback équipe seule.
MIN_PLAYERS_FOR_LAYER = 8

# Standardisation des composantes (correction 3) : chaque composante est ramenée
# en z-score (écarts-types à la moyenne de population) AVANT d'être combinée, avec
# un poids par composante. Buts/xG plus lourds que les passes brutes. L'échelle est
# ajustée une seule fois sur la population pré-tournoi (date < cutoff) -> sans fuite.
COMPONENT_WEIGHTS = {
    # attaque
    "goals": 1.0, "xg": 1.0, "assists": 0.7, "xa": 0.7, "key_passes": 0.4, "chances_created": 0.4,
    # milieu (key_passes déjà ci-dessus)
    "prog_passes": 0.7, "recoveries": 0.6, "pass_pct_pressure": 0.5,
    # défense
    "tackles": 0.7, "interceptions": 0.7, "duels_won": 0.6, "clearances": 0.4, "xg_against": 1.0,
}
NORMALIZER_FIT_CUTOFF = WC2026_START     # échelle ajustée sur la population pré-tournoi

# ---------------------------------------------------------------------------
# Couplage — tilt borné (brief §4)
# ---------------------------------------------------------------------------
# λ_ajusté = λ_base * (1 + w * tilt), tilt centré (forme normale -> 0).
PLAYER_TILT_WEIGHT = 0.15               # w : poids borné
PLAYER_TILT_CLIP = 1.0                  # |tilt| <= 1 -> |variation λ| <= 15 %
MID_TILT_WEIGHT = 0.5                   # κ : poids du différentiel de milieu (correction 2)

# ---------------------------------------------------------------------------
# Module 3 — Monte Carlo
# ---------------------------------------------------------------------------
MC_SEED = 42
MC_N_SIMS = 50_000

# ---------------------------------------------------------------------------
# Elo (recalculé depuis source A — cohérence/contre-vérification, pas source des buts)
# ---------------------------------------------------------------------------
ELO_BASE = 1500.0
ELO_K = 20.0                            # K-factor de base
ELO_HOME_ADV = 65.0                     # bonus terrain (points Elo) si non neutre
ELO_GOAL_DIFF_SCALING = True            # ajustement par écart de buts (style World Football Elo)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
OVER_UNDER_LINES = (1.5, 2.5, 3.5)
RELIABILITY_BINS = 10

# ---------------------------------------------------------------------------
# Collecteur de snapshots marché (the-odds-api, source G) — le juge qui s'accumule
# ---------------------------------------------------------------------------
ODDS_SPORT_KEY = "soccer_fifa_world_cup"
ODDS_MARKETS = "h2h"            # juge principal (1X2). "totals" optionnel (double le coût quota).
ODDS_REGIONS = "uk,eu"
ODDS_FORMAT = "decimal"
SNAPSHOT_HORIZON_HOURS = 72     # ne figer que les matchs à <= 72 h du coup d'envoi
# Exchanges « sharp » à préférer (confirmés par le probe G : betfair_ex_*, matchbook).
PREFERRED_SHARP_BOOKS = ["betfair_ex_uk", "betfair_ex_eu", "matchbook"]
DATE_MATCH_TOLERANCE_DAYS = 1   # tolérance de jointure fixture (fuseaux : commence_time UTC)
TEAM_NAME_MAP = {               # surcharges nom the-odds-api -> nom results.csv
    "USA": "United States",
    "Czechia": "Czech Republic",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}
