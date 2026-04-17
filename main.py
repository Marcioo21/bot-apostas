#!/usr/bin/env python3
"""
Sistema Profissional de Análise de Futebol – Pré‑Jogo e Alertas Ao Vivo

Uso:
    python script.py          # Relatório diário de odds e palpites (pré‑jogo)
    python script.py --live   # Monitoramento contínuo (alerta por jogo quando oportunidade)
"""

import logging
import os
import re
import difflib
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ----------------------------------------------------------------------
# Configuração de Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

load_dotenv()

# ----------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")

ODDS_URL = "https://www.oddsportal.com/matches/"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# Mapeamento de ligas → código da API
COMPETITION_MAP: Dict[Tuple[str, str], str] = {
    ("Inglaterra", "Premier League"): "PL",
    ("Espanha", "LaLiga"): "PD",
    ("Itália", "Serie A"): "SA",
    ("Alemanha", "Bundesliga"): "BL1",
    ("França", "Ligue 1"): "FL1",
    ("Holanda", "Eredivisie"): "DED",
    ("Portugal", "Primeira Liga"): "PPL",
    ("Brasil", "Brasileirão Série A"): "BSA",
    ("Europa", "Liga dos Campeões"): "CL",
    ("Europa", "Liga Europa"): "ELC",
}

TEAM_ALIASES: Dict[str, str] = {
    "Manchester Utd": "Manchester United FC",
    "Man Utd": "Manchester United FC",
    "Inter": "FC Internazionale Milano",
    "Milan": "AC Milan",
    "Roma": "AS Roma",
    "Lazio": "SS Lazio",
    "Leeds": "Leeds United FC",
    "Getafe": "Getafe CF",
    "Fiorentina": "ACF Fiorentina",
}

# Ligas principais para o modo pré‑jogo
MAIN_LEAGUES: set = {
    ("Inglaterra", "Premier League"),
    ("Espanha", "LaLiga"),
    ("Itália", "Serie A"),
    ("Alemanha", "Bundesliga"),
    ("França", "Ligue 1"),
    ("Holanda", "Eredivisie"),
    ("Portugal", "Primeira Liga"),
    ("Brasil", "Brasileirão Série A"),
    ("Europa", "Liga dos Campeões"),
    ("Europa", "Liga Europa"),
}

# Competições monitoradas no modo ao vivo
LIVE_COMPETITIONS = [
    {"name": "Premier League", "code": "PL", "id": 2021},
    {"name": "LaLiga", "code": "PD", "id": 2019},
    {"name": "Serie A", "code": "SA", "id": 2015},
    {"name": "Bundesliga", "code": "BL1", "id": 2002},
    {"name": "Ligue 1", "code": "FL1", "id": 2014},
    {"name": "Eredivisie", "code": "DED", "id": 2003},
    {"name": "Primeira Liga", "code": "PPL", "id": 2017},
    {"name": "Brasileirão Série A", "code": "BSA", "id": 2016},
    {"name": "Champions League", "code": "CL", "id": 2001},
    {"name": "Europa League", "code": "ELC", "id": 2146},
]

# Estatísticas médias por liga (personalizáveis)
LEAGUE_STATS = {
    "PL": {"avg_cards": 3.8, "avg_corners": 10.2},
    "PD": {"avg_cards": 4.5, "avg_corners": 9.5},
    "SA": {"avg_cards": 4.2, "avg_corners": 9.8},
    "BL1": {"avg_cards": 3.9, "avg_corners": 10.5},
    "FL1": {"avg_cards": 3.7, "avg_corners": 9.0},
    "DED": {"avg_cards": 3.2, "avg_corners": 10.8},
    "PPL": {"avg_cards": 4.8, "avg_corners": 10.0},
    "BSA": {"avg_cards": 4.5, "avg_corners": 10.5},
    "CL":  {"avg_cards": 4.0, "avg_corners": 9.8},
    "ELC": {"avg_cards": 4.1, "avg_corners": 9.5},
}

# ----------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------
@dataclass
class Match:
    hora: str
    country: str
    league: str
    home: str
    away: str
    odd_1: float
    odd_x: float
    odd_2: float


@dataclass
class TeamStats:
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    ppg: float = 0.0
    gd_per_game: float = 0.0
    win_rate: float = 0.0
    draw_rate: float = 0.0
    loss_rate: float = 0.0


@dataclass
class MatchAnalysis:
    probabilities: Optional[Dict[str, float]] = None
    home_stats: Optional[TeamStats] = None
    away_stats: Optional[TeamStats] = None
    reason: Optional[str] = None


# ----------------------------------------------------------------------
# Telegram (com Markdown)
# ----------------------------------------------------------------------
def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    if not TOKEN or not CHAT_ID:
        logger.error("Token/Chat ID do Telegram não definidos")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Erro Telegram: {e}")
        return False


# ----------------------------------------------------------------------
# Scraping OddsPortal (pré-jogo)
# ----------------------------------------------------------------------
def fetch_odds_page_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900}
        )
        logger.info("Acessando OddsPortal...")
        page.goto(ODDS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        text = page.locator("body").inner_text()
        browser.close()
        return text


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_team_name(name: str) -> str:
    name = clean_text(name).replace("–", "").replace("-", " - ").strip()
    return TEAM_ALIASES.get(name, name)


def extract_country_and_league(lines: List[str], start_idx: int) -> Tuple[str, str]:
    back = lines[max(0, start_idx - 8):start_idx]
    filtered = [
        line for line in back
        if line not in {"/", "Futebol", "Basquete", "Tênis", "Vôlei", "Mais"}
    ]
    country = filtered[-2] if len(filtered) >= 2 else ""
    league = filtered[-1] if len(filtered) >= 1 else ""
    return country, league


def parse_matches(page_text: str) -> List[Match]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    matches: List[Match] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "1" and i + 7 < len(lines):
            if lines[i + 1] == "X" and lines[i + 2] == "2":
                country, league = extract_country_and_league(lines, i)
                j = i + 3
                if j < len(lines) and ("Hoje" in lines[j] or re.search(r"\d{1,2}\s+\w{3}", lines[j])):
                    j += 1
                if j < len(lines) and re.match(r"^\d{1,2}:\d{2}$", lines[j]):
                    hora = lines[j]
                    j += 1
                else:
                    i += 1
                    continue
                if j < len(lines):
                    home = clean_team_name(lines[j])
                    j += 1
                else:
                    i += 1
                    continue
                if j < len(lines) and lines[j] in {"–", "-"}:
                    j += 1
                if j < len(lines):
                    away = clean_team_name(lines[j])
                    j += 1
                else:
                    i += 1
                    continue
                if j + 2 < len(lines):
                    odd1, oddx, odd2 = lines[j], lines[j + 1], lines[j + 2]
                    if all(re.match(r"^\d+(\.\d+)?$", o) for o in (odd1, oddx, odd2)):
                        matches.append(Match(
                            hora=hora, country=country, league=league,
                            home=home, away=away,
                            odd_1=float(odd1), odd_x=float(oddx), odd_2=float(odd2)
                        ))
                        i = j + 3
                        continue
        i += 1

    unique: List[Match] = []
    seen = set()
    for m in matches:
        key = (m.hora, m.country, m.league, m.home, m.away, m.odd_1, m.odd_x, m.odd_2)
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


# ----------------------------------------------------------------------
# API football-data.org
# ----------------------------------------------------------------------
def football_data_request(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    if not FOOTBALL_DATA_API_KEY:
        return None
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        resp = requests.get(f"{FOOTBALL_DATA_BASE}{path}", headers=headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Erro API: {e}")
        return None


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9à-ÿ ]+", " ", name)
    name = re.sub(r"\b(fc|cf|ac|sc|fk|club|calcio|ud|afc|as|ss)\b", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def get_competition_code(country: str, league: str) -> Optional[str]:
    return COMPETITION_MAP.get((country, league))


def get_competition_teams(competition_code: str) -> List[Dict]:
    data = football_data_request(f"/competitions/{competition_code}/teams")
    return data.get("teams", []) if data else []


def resolve_team_id(team_name: str, teams: List[Dict]) -> Optional[int]:
    if not teams:
        return None
    target = normalize_name(TEAM_ALIASES.get(team_name, team_name))
    name_map = {}
    for team in teams:
        for cand in (team.get("name"), team.get("shortName"), team.get("tla")):
            if cand:
                name_map[normalize_name(cand)] = team["id"]
    if target in name_map:
        return name_map[target]
    matches = difflib.get_close_matches(target, list(name_map.keys()), n=1, cutoff=0.6)
    return name_map[matches[0]] if matches else None


def get_last_5_matches(team_id: int, venue: str) -> List[Dict]:
    today = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=240)
    data = football_data_request(
        f"/teams/{team_id}/matches",
        params={
            "status": "FINISHED",
            "venue": venue,
            "dateFrom": date_from.isoformat(),
            "dateTo": today.isoformat()
        }
    )
    if not data:
        return []
    matches = data.get("matches", [])
    matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    return matches[:5]


def compute_team_stats(matches: List[Dict], venue: str) -> TeamStats:
    wins = draws = losses = 0
    goals_for = goals_against = 0
    for m in matches:
        home_g = m.get("score", {}).get("fullTime", {}).get("home")
        away_g = m.get("score", {}).get("fullTime", {}).get("away")
        if home_g is None or away_g is None:
            continue
        if venue == "HOME":
            gf, ga = home_g, away_g
        else:
            gf, ga = away_g, home_g
        goals_for += gf
        goals_against += ga
        if gf > ga:
            wins += 1
        elif gf == ga:
            draws += 1
        else:
            losses += 1
    games = wins + draws + losses
    if games == 0:
        return TeamStats()
    points = wins * 3 + draws
    return TeamStats(
        games=games,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=goals_for,
        goals_against=goals_against,
        ppg=points / games,
        gd_per_game=(goals_for - goals_against) / games,
        win_rate=wins / games,
        draw_rate=draws / games,
        loss_rate=losses / games,
    )


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def gd_score(gd_per_game: float) -> float:
    return clamp((gd_per_game + 2) / 4, 0.0, 1.0)


def calculate_probabilities(home_stats: TeamStats, away_stats: TeamStats) -> Dict[str, float]:
    home_strength = (
        1.00
        + 1.80 * home_stats.win_rate
        + 0.90 * away_stats.loss_rate
        + 0.70 * gd_score(home_stats.gd_per_game)
        + 0.40 * (home_stats.ppg / 3)
    )
    away_strength = (
        1.00
        + 1.80 * away_stats.win_rate
        + 0.90 * home_stats.loss_rate
        + 0.70 * gd_score(away_stats.gd_per_game)
        + 0.40 * (away_stats.ppg / 3)
    )
    balance = 1.0 - clamp(abs(home_stats.gd_per_game - away_stats.gd_per_game) / 2.5, 0.0, 1.0)
    draw_strength = (
        0.90
        + 1.70 * ((home_stats.draw_rate + away_stats.draw_rate) / 2)
        + 0.50 * balance
    )
    total = home_strength + draw_strength + away_strength
    p1 = round((home_strength / total) * 100, 1)
    px = round((draw_strength / total) * 100, 1)
    p2 = round((away_strength / total) * 100, 1)
    diff = round(100.0 - (p1 + px + p2), 1)
    p1 = round(p1 + diff, 1)
    return {"p1": p1, "px": px, "p2": p2}


def fair_odds_from_prob(prob_pct: float) -> float:
    return round(100 / prob_pct, 2) if prob_pct > 0 else 0.0


def analyze_match(match: Match) -> MatchAnalysis:
    analysis = MatchAnalysis()
    if not FOOTBALL_DATA_API_KEY:
        analysis.reason = "API key não configurada"
        return analysis
    code = get_competition_code(match.country, match.league)
    if not code:
        analysis.reason = f"Liga não mapeada: {match.country}/{match.league}"
        return analysis
    teams = get_competition_teams(code)
    if not teams:
        analysis.reason = f"Sem times para {code}"
        return analysis
    hid = resolve_team_id(match.home, teams)
    aid = resolve_team_id(match.away, teams)
    if not hid or not aid:
        analysis.reason = "Time não identificado"
        return analysis
    home_m = get_last_5_matches(hid, "HOME")
    away_m = get_last_5_matches(aid, "AWAY")
    hs = compute_team_stats(home_m, "HOME")
    aws = compute_team_stats(away_m, "AWAY")
    analysis.home_stats = hs
    analysis.away_stats = aws
    if hs.games < 3 or aws.games < 3:
        analysis.reason = "Amostra insuficiente (<3 jogos)"
        return analysis
    analysis.probabilities = calculate_probabilities(hs, aws)
    return analysis


# ----------------------------------------------------------------------
# Palpite Multicritério (Pré-Jogo)
# ----------------------------------------------------------------------
def normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
    total = sum(scores.values())
    if total == 0:
        return {k: 0.0 for k in scores}
    return {k: v / total for k, v in scores.items()}


def calculate_criteria_scores(match: Match, analysis: MatchAnalysis) -> Dict[str, Dict[str, float]]:
    scores = {}
    probs = analysis.probabilities
    home_stats = analysis.home_stats
    away_stats = analysis.away_stats

    if not probs or not home_stats or not away_stats:
        return scores

    fair_1 = fair_odds_from_prob(probs['p1'])
    fair_x = fair_odds_from_prob(probs['px'])
    fair_2 = fair_odds_from_prob(probs['p2'])

    scores['Probabilidade'] = {
        '1': probs['p1'] / 100.0,
        'X': probs['px'] / 100.0,
        '2': probs['p2'] / 100.0
    }

    value_1 = max(0, (match.odd_1 / fair_1) - 1.0) if fair_1 > 0 else 0
    value_X = max(0, (match.odd_x / fair_x) - 1.0) if fair_x > 0 else 0
    value_2 = max(0, (match.odd_2 / fair_2) - 1.0) if fair_2 > 0 else 0
    scores['Value'] = normalize_scores({'1': value_1, 'X': value_X, '2': value_2})

    if home_stats.ppg > 0 or away_stats.ppg > 0:
        total_ppg = home_stats.ppg + away_stats.ppg
        if total_ppg > 0:
            strength_1 = home_stats.ppg / total_ppg
            strength_2 = away_stats.ppg / total_ppg
        else:
            strength_1 = strength_2 = 0.5
        strength_X = (strength_1 + strength_2) / 3
        scores['Força (PPG)'] = normalize_scores({'1': strength_1, 'X': strength_X, '2': strength_2})
    else:
        scores['Força (PPG)'] = {'1': 0.33, 'X': 0.33, '2': 0.34}

    home_gf_avg = home_stats.goals_for / home_stats.games if home_stats.games > 0 else 1.0
    away_gf_avg = away_stats.goals_for / away_stats.games if away_stats.games > 0 else 1.0
    gf_total = home_gf_avg + away_gf_avg
    if gf_total > 0:
        mom_1 = home_gf_avg / gf_total
        mom_2 = away_gf_avg / gf_total
        mom_X = 1 - abs(mom_1 - mom_2)
    else:
        mom_1 = mom_X = mom_2 = 0.33
    scores['Momento (Gols)'] = normalize_scores({'1': mom_1, 'X': mom_X, '2': mom_2})

    home_ga_avg = home_stats.goals_against / home_stats.games if home_stats.games > 0 else 1.0
    away_ga_avg = away_stats.goals_against / away_stats.games if away_stats.games > 0 else 1.0
    inv_home_def = 1.0 / (1.0 + home_ga_avg)
    inv_away_def = 1.0 / (1.0 + away_ga_avg)
    scores['Defesa'] = normalize_scores({
        '1': inv_home_def,
        '2': inv_away_def,
        'X': (inv_home_def + inv_away_def) / 2
    })

    return scores


def generate_bet_tip(match: Match, analysis: MatchAnalysis) -> str:
    if not analysis.probabilities or not analysis.home_stats or not analysis.away_stats:
        return "⚪ Sem dados suficientes"

    weights = {
        'Probabilidade': 0.30,
        'Value': 0.25,
        'Força (PPG)': 0.20,
        'Momento (Gols)': 0.15,
        'Defesa': 0.10
    }

    criteria_scores = calculate_criteria_scores(match, analysis)
    if not criteria_scores:
        return "⚪ Sem dados"

    final_scores = {'1': 0.0, 'X': 0.0, '2': 0.0}
    for criterion, scores in criteria_scores.items():
        w = weights.get(criterion, 0.0)
        for outcome in ['1', 'X', '2']:
            final_scores[outcome] += scores.get(outcome, 0.0) * w

    max_outcome = max(final_scores, key=final_scores.get)
    confidence = final_scores[max_outcome]

    if confidence >= 0.70:
        stars = "⭐⭐⭐"
    elif confidence >= 0.55:
        stars = "⭐⭐"
    elif confidence >= 0.40:
        stars = "⭐"
    else:
        stars = "⚪ Baixa"

    outcome_text = {
        '1': f"Vitória do {match.home}",
        'X': "Empate",
        '2': f"Vitória do {match.away}"
    }

    main_contributors = [c for c, s in criteria_scores.items() if s[max_outcome] >= 0.45]
    justif = f"Baseado em: {', '.join(main_contributors[:3])}" if main_contributors else "Combinação equilibrada"

    return f"{outcome_text[max_outcome]} | Confiança {stars} ({confidence*100:.1f}%)\n   └─ {justif}"


# ----------------------------------------------------------------------
# Formatação Pré‑Jogo
# ----------------------------------------------------------------------
def format_match_block(match: Match, analysis: MatchAnalysis, index: int) -> str:
    lines = [
        f"*⚽ Jogo {index}*",
        f"🕒 `{match.hora}`",
        f"🏆 *{match.country} / {match.league}*",
        f"🏟️ *{match.home}*  x  *{match.away}*",
        f"💰 Odds: `{match.odd_1:.2f}` | `{match.odd_x:.2f}` | `{match.odd_2:.2f}`"
    ]
    if analysis.probabilities:
        p = analysis.probabilities
        lines.append(f"📈 Prob: `{p['p1']}%` | `{p['px']}%` | `{p['p2']}%`")
        if analysis.home_stats:
            hs = analysis.home_stats
            lines.append(f"🏠 Casa: {hs.wins}V {hs.draws}E {hs.losses}D | GP {hs.goals_for} GC {hs.goals_against}")
        if analysis.away_stats:
            aw = analysis.away_stats
            lines.append(f"🛫 Fora: {aw.wins}V {aw.draws}E {aw.losses}D | GP {aw.goals_for} GC {aw.goals_against}")
        fair1 = fair_odds_from_prob(p['p1'])
        fairx = fair_odds_from_prob(p['px'])
        fair2 = fair_odds_from_prob(p['p2'])
        lines.append(f"🎯 Odds justas: `{fair1:.2f}` | `{fairx:.2f}` | `{fair2:.2f}`")
        tip = generate_bet_tip(match, analysis)
        lines.append(f"🤖 *PALPITE:* {tip}")
    else:
        lines.append(f"⚠️ Indisponível: {analysis.reason}")
    lines.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def split_into_messages(matches: List[Match], analyses: List[MatchAnalysis]) -> List[str]:
    messages = []
    current = "*🔥 ANÁLISE PRÉ‑JOGO – PRINCIPAIS LIGAS 🔥*\n\n"
    for idx, (m, a) in enumerate(zip(matches, analyses), 1):
        block = format_match_block(m, a, idx)
        if len(current) + len(block) > 3500:
            messages.append(current)
            current = "*🔥 CONTINUAÇÃO 🔥*\n\n" + block
        else:
            current += block
    footer = f"\n📊 *Total:* {len(matches)} jogos\n🧠 Palpite sempre exibido (confiança indicada)"
    if len(current) + len(footer) <= 3500:
        current += footer
    else:
        messages.append(current)
        current = footer
    if current.strip():
        messages.append(current)
    return messages


# ----------------------------------------------------------------------
# Modo Ao Vivo (Alertas por Oportunidade)
# ----------------------------------------------------------------------
# Cache de alertas enviados: chave = match_id + tipo_alerta
sent_alerts = set()

def get_live_matches() -> List[Dict]:
    live_matches = []
    for comp in LIVE_COMPETITIONS:
        data = football_data_request(
            f"/competitions/{comp['code']}/matches",
            params={"status": "LIVE"}
        )
        if data and "matches" in data:
            for m in data["matches"]:
                m["competition_name"] = comp["name"]
                m["competition_code"] = comp["code"]
            live_matches.extend(data["matches"])
    return live_matches


def fetch_team_recent_stats(team_id: int, venue: str) -> Tuple[float, float, float]:
    matches = get_last_5_matches(team_id, venue)
    stats = compute_team_stats(matches, venue)
    if stats.games == 0:
        return 1.0, 1.0, 1.0
    return stats.goals_for / stats.games, stats.goals_against / stats.games, stats.ppg


def estimate_cards(match: Dict) -> Dict:
    """
    Retorna:
        text: descrição do palpite
        confidence: probabilidade estimada (0-1)
        alert: True se deve gerar alerta (confidence >= threshold)
    """
    home_id = match["homeTeam"]["id"]
    away_id = match["awayTeam"]["id"]
    comp_code = match.get("competition_code", "PL")
    minute = match.get("minute", 0) or 0

    stats = LEAGUE_STATS.get(comp_code, {"avg_cards": 4.0})
    base_cards = stats["avg_cards"]

    if minute > 0:
        expected = base_cards * (minute / 90)
    else:
        expected = base_cards

    _, home_ga, _ = fetch_team_recent_stats(home_id, "HOME")
    _, away_ga, _ = fetch_team_recent_stats(away_id, "AWAY")
    fragility = (home_ga + away_ga) / 2.5
    expected *= fragility

    # Converter expected em confiança para "mais de 4.5 cartões"
    if expected >= 5.0:
        confidence = min(0.95, 0.6 + (expected - 4.5) * 0.2)
        text = f"🟨 *MAIS DE 4.5 CARTÕES* (projeção: {expected:.1f})"
        alert = confidence >= 0.70
    elif expected <= 3.0:
        confidence = min(0.95, 0.6 + (3.0 - expected) * 0.2)
        text = f"🟨 *MENOS DE 3.5 CARTÕES* (projeção: {expected:.1f})"
        alert = confidence >= 0.70
    else:
        confidence = 0.0
        text = f"🟨 Cartões dentro da média (~{base_cards:.1f})"
        alert = False

    return {"text": text, "confidence": confidence, "alert": alert, "type": "cards"}


def estimate_corners(match: Dict) -> Dict:
    home_id = match["homeTeam"]["id"]
    away_id = match["awayTeam"]["id"]
    comp_code = match.get("competition_code", "PL")
    minute = match.get("minute", 0) or 0

    stats = LEAGUE_STATS.get(comp_code, {"avg_corners": 10.0})
    base_corners = stats["avg_corners"]

    home_gf, _, _ = fetch_team_recent_stats(home_id, "HOME")
    away_gf, _, _ = fetch_team_recent_stats(away_id, "AWAY")
    offensive = (home_gf + away_gf) / 2.5

    if minute > 0:
        expected = base_corners * offensive * (minute / 90)
    else:
        expected = base_corners * offensive

    if expected >= 11.0:
        confidence = min(0.95, 0.6 + (expected - 10.0) * 0.2)
        text = f"📐 *MAIS DE 10.5 ESCANTEIOS* (projeção: {expected:.1f})"
        alert = confidence >= 0.70
    elif expected <= 7.0:
        confidence = min(0.95, 0.6 + (7.0 - expected) * 0.2)
        text = f"📐 *MENOS DE 8.5 ESCANTEIOS* (projeção: {expected:.1f})"
        alert = confidence >= 0.70
    else:
        confidence = 0.0
        text = f"📐 Escanteios na faixa de 8‑10"
        alert = False

    return {"text": text, "confidence": confidence, "alert": alert, "type": "corners"}


def estimate_next_goal(match: Dict) -> Dict:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_id = match["homeTeam"]["id"]
    away_id = match["awayTeam"]["id"]
    score = match["score"]["fullTime"]
    home_goals = score["home"] if score["home"] is not None else 0
    away_goals = score["away"] if score["away"] is not None else 0

    home_ppg = fetch_team_recent_stats(home_id, "HOME")[2]
    away_ppg = fetch_team_recent_stats(away_id, "AWAY")[2]

    if home_goals > away_goals:
        prob_home = 0.40
        prob_away = 0.35
    elif away_goals > home_goals:
        prob_home = 0.55
        prob_away = 0.30
    else:
        prob_home = 0.50
        prob_away = 0.35

    prob_home *= (home_ppg / 2.0)
    prob_away *= (away_ppg / 2.0)
    total = prob_home + prob_away + 0.20

    p_home = prob_home / total
    p_away = prob_away / total

    if p_home > 0.55:
        confidence = p_home
        text = f"⚽ Próximo gol: *{home}* ({p_home*100:.0f}%)"
        alert = confidence >= 0.70
    elif p_away > 0.50:
        confidence = p_away
        text = f"⚽ Próximo gol: *{away}* ({p_away*100:.0f}%)"
        alert = confidence >= 0.70
    else:
        confidence = 0.0
        text = "⚽ Próximo gol: equilibrado"
        alert = False

    return {"text": text, "confidence": confidence, "alert": alert, "type": "next_goal"}


def generate_alert_message(match: Dict, alerts: List[Dict]) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    score = match["score"]["fullTime"]
    home_goals = score["home"] if score["home"] is not None else 0
    away_goals = score["away"] if score["away"] is not None else 0
    minute = match.get("minute", 0) or 0
    comp_name = match.get("competition_name", "Liga")

    lines = [
        f"🔴 *ALERTA DE OPORTUNIDADE AO VIVO* 🔴",
        f"⚡ *{home} {home_goals} x {away_goals} {away}*",
        f"🏆 {comp_name}  |  ⏱️ `{minute}'`",
        ""
    ]
    for alert in alerts:
        lines.append(alert["text"])
    lines.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def send_initial_live_status(live_matches: List[Dict]):
    """Envia uma mensagem inicial informando quais partidas estão sendo monitoradas ao vivo."""
    if not live_matches:
        msg = "🟢 *Monitoramento Ao Vivo Iniciado*\n\nNenhuma partida ao vivo no momento. Aguardando início de jogos nas ligas monitoradas."
    else:
        lines = ["🔴 *MONITORAMENTO AO VIVO INICIADO* 🔴", ""]
        lines.append(f"🎮 Acompanhando *{len(live_matches)}* partida(s) neste momento:", "")
        for m in live_matches:
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            score = m["score"]["fullTime"]
            home_goals = score["home"] if score["home"] is not None else 0
            away_goals = score["away"] if score["away"] is not None else 0
            minute = m.get("minute", 0) or 0
            comp = m.get("competition_name", "Liga")
            lines.append(f"⚽ *{home}* {home_goals} x {away_goals} *{away}*")
            lines.append(f"   └─ 🏆 {comp}  |  ⏱️ `{minute}'`")
            lines.append("")
        lines.append("📡 *Alertas serão enviados quando surgirem oportunidades.*")
        msg = "\n".join(lines)
    send_telegram(msg)


def live_mode():
    logger.info("🚀 Modo Ao Vivo (alertas por jogo) iniciado. Verificando a cada 60 segundos...")
    # Primeira verificação para enviar status inicial
    try:
        initial_matches = get_live_matches()
        send_initial_live_status(initial_matches)
    except Exception as e:
        logger.exception("Erro ao obter status inicial. Continuando...")

    while True:
        try:
            live_matches = get_live_matches()
            if not live_matches:
                logger.info("Nenhuma partida ao vivo no momento.")
            else:
                for match in live_matches:
                    match_id = match["id"]
                    # Coleta todos os palpites com flag alert
                    cards = estimate_cards(match)
                    corners = estimate_corners(match)
                    next_goal = estimate_next_goal(match)

                    alerts_to_send = []
                    for tip in (cards, corners, next_goal):
                        if tip["alert"]:
                            alert_key = f"{match_id}_{tip['type']}"
                            if alert_key not in sent_alerts:
                                alerts_to_send.append(tip)
                                sent_alerts.add(alert_key)

                    if alerts_to_send:
                        msg = generate_alert_message(match, alerts_to_send)
                        send_telegram(msg)
                        logger.info(f"Alerta enviado para {match['homeTeam']['name']} x {match['awayTeam']['name']}")
            time.sleep(60)  # verifica a cada minuto
        except KeyboardInterrupt:
            logger.info("Encerrado pelo usuário.")
            break
        except Exception as e:
            logger.exception("Erro no loop ao vivo. Aguardando 30s...")
            time.sleep(30)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if "--live" in sys.argv:
        live_mode()
        return

    try:
        page_text = fetch_odds_page_text()
        matches = parse_matches(page_text)
        logger.info(f"Partidas encontradas: {len(matches)}")

        matches = [m for m in matches if (m.country, m.league) in MAIN_LEAGUES]
        logger.info(f"Partidas nas ligas principais: {len(matches)}")

        if not matches:
            logger.warning("Nenhuma partida após filtro.")
            return

        analyses = [analyze_match(m) for m in matches]
        messages = split_into_messages(matches, analyses)
        for msg in messages:
            if not send_telegram(msg):
                logger.error("Falha no envio de uma das mensagens.")
    except Exception as e:
        logger.exception("Erro fatal.")


if __name__ == "__main__":
    main()