import requests
import time
import json
import os
import logging
from datetime import datetime

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Config
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
CHAT_ID          = os.environ.get("CHAT_ID", "")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_KEY", "")
POLL_INTERVAL    = 1200        # check every 20 minutes
MIN_CONFIDENCE   = 65          # only alert if confidence >= 65%
MAX_VOLUME       = 1000000     # ignore tiny markets under $1M volume
PAPER_TRADE_FILE = "paper_trades.json"
DAILY_LOSS_LIMIT = 0.05        # stop if down 5% in a day
DRAWDOWN_LIMIT   = 0.20        # pause if down 20% from peak

# Paper trading bankroll
STARTING_BANKROLL = 1000.0

# Storage

def load_trades():
    if os.path.exists(PAPER_TRADE_FILE):
        with open(PAPER_TRADE_FILE, "r") as f:
            return json.load(f)
    return {
        "bankroll": STARTING_BANKROLL,
        "trades": [],
        "stats": {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "pending": 0,
            "profit": 0.0,
            "peak_bankroll": STARTING_BANKROLL
        }
    }

def save_trades(data):
    with open(PAPER_TRADE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Polymarket API

def fetch_markets():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 50,
        "order": "volume",
        "ascending": "false"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            markets = r.json()
            log.info("Fetched " + str(len(markets)) + " markets from Polymarket")
            return markets
        else:
            log.error("Polymarket API error: " + str(r.status_code))
            return []
    except Exception as e:
        log.error("Failed to fetch markets: " + str(e))
        return []

def filter_markets(markets):
    good = []
    for m in markets:
        try:
            if not m.get("question"):
                continue

            volume = float(m.get("volume", 0) or 0)
            if volume < MAX_VOLUME:
                continue

            end_date = m.get("endDate") or m.get("endDateIso")
            if end_date:
                try:
                    end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    now = datetime.now(end.tzinfo)
                    hours_left = (end - now).total_seconds() / 3600
                    if hours_left < 1 or hours_left > 168:
                        continue
                except Exception:
                    pass

            outcomes = m.get("outcomes")
            prices = m.get("outcomePrices")
            if outcomes and prices:
                try:
                    price_list = json.loads(prices) if isinstance(prices, str) else prices
                    if len(price_list) == 2:
                        p1 = float(price_list[0])
                        p2 = float(price_list[1])
                        if 0.38 <= p1 <= 0.62 and 0.38 <= p2 <= 0.62:
                            continue
                except Exception:
                    pass

            good.append(m)

        except Exception as e:
            log.warning("Error filtering market: " + str(e))
            continue

    log.info("Filtered to " + str(len(good)) + " quality markets")
    return good

# Claude API

def research_market(market):
    question = market.get("question", "")
    description = market.get("description", "")
    outcomes = market.get("outcomes", "[]")
    prices = market.get("outcomePrices", "[]")

    try:
        outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        price_list = json.loads(prices) if isinstance(prices, str) else prices
    except Exception:
        outcome_list = []
        price_list = []

    context = "Question: " + question + "\n"
    if description:
        context += "Description: " + description[:500] + "\n"
    if outcome_list and price_list:
        context += "Current market odds:\n"
        for i, outcome in enumerate(outcome_list):
            if i < len(price_list):
                prob = float(price_list[i]) * 100
                context += "  " + str(outcome) + ": " + str(round(prob, 1)) + "%\n"

    prompt = """You are an expert prediction market analyst. Research this Polymarket question and give your assessment.

""" + context + """

Analyze this question carefully using your knowledge. Consider:
1. Current real-world situation and recent developments
2. Historical base rates and precedents
3. Expert consensus and reliable indicators
4. What the market odds imply vs what you think is accurate

Respond in this EXACT format (JSON only, no other text):
{
  "pick": "YES or NO or the exact outcome name",
  "confidence": 75,
  "edge": 15,
  "reasoning": "2-3 sentence explanation of why",
  "risk_factors": "main thing that could make you wrong",
  "skip": false
}

If you cannot research this reliably or it is purely random, set skip to true.
Confidence is your probability estimate (0-100). Edge is confidence minus market implied probability."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )

        if r.status_code == 200:
            content = r.json()["content"][0]["text"].strip()
            content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
            return result
        else:
            log.error("Claude API error: " + str(r.status_code) + " " + r.text[:200])
            return None

    except json.JSONDecodeError as e:
        log.error("JSON parse error from Claude: " + str(e))
        return None
    except Exception as e:
        log.error("Claude research failed: " + str(e))
        return None

# Risk Management

def check_risk_limits(data):
    bankroll = data["bankroll"]
    peak = data["stats"].get("peak_bankroll", STARTING_BANKROLL)

    if bankroll > peak:
        data["stats"]["peak_bankroll"] = bankroll
        peak = bankroll

    drawdown = (peak - bankroll) / peak
    if drawdown >= DRAWDOWN_LIMIT:
        msg = (
            "🚨 DRAWDOWN ALERT\n\n"
            "Bankroll dropped " + str(round(drawdown * 100, 1)) + "% from peak\n"
            "Peak: $" + str(round(peak, 2)) + "\n"
            "Current: $" + str(round(bankroll, 2)) + "\n\n"
            "Bot paused. Review before continuing."
        )
        send_telegram(msg)
        log.warning("Drawdown limit hit: " + str(round(drawdown * 100, 1)) + "%")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    daily_loss = 0.0
    for t in data["trades"]:
        if t.get("status") == "lost" and t.get("timestamp", "").startswith(today):
            daily_loss += t.get("bet_size", 0)

    daily_loss_pct = daily_loss / STARTING_BANKROLL
    if daily_loss_pct >= DAILY_LOSS_LIMIT:
        msg = (
            "⛔ DAILY LOSS LIMIT HIT\n\n"
            "Lost " + str(round(daily_loss_pct * 100, 1)) + "% today\n"
            "Amount: $" + str(round(daily_loss, 2)) + "\n\n"
            "No more bets today. Resumes tomorrow."
        )
        send_telegram(msg)
        log.warning("Daily loss limit hit")
        return False

    return True

# Paper Trading

def calculate_bet_size(bankroll, confidence, edge):
    if edge <= 0:
        return 0
    kelly = (edge / 100) / (1 - confidence / 100 + 0.001)
    fractional_kelly = kelly * 0.25
    bet = bankroll * fractional_kelly
    max_bet = bankroll * 0.05
    return round(min(bet, max_bet), 2)

def place_paper_trade(market, research, data):
    bankroll = data["bankroll"]
    confidence = research["confidence"]
    edge = research["edge"]
    bet_size = calculate_bet_size(bankroll, confidence, edge)

    if bet_size < 1:
        return None

    trade = {
        "id": market.get("id", "unknown"),
        "question": market.get("question", ""),
        "pick": research["pick"],
        "confidence": confidence,
        "edge": edge,
        "reasoning": research["reasoning"],
        "risk_factors": research["risk_factors"],
        "bet_size": bet_size,
        "potential_profit": round(bet_size * (edge / 100), 2),
        "timestamp": datetime.now().isoformat(),
        "end_date": market.get("endDate") or market.get("endDateIso", ""),
        "status": "pending",
        "result": None
    }

    data["trades"].append(trade)
    data["stats"]["total"] += 1
    data["stats"]["pending"] += 1
    save_trades(data)

    return trade

# Telegram

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("No Telegram config, printing to console:")
        print(text)
        return True
    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=15)
        return r.status_code == 200
    except Exception as e:
        log.error("Telegram send failed: " + str(e))
        return False

def format_pick(trade, market):
    volume = float(market.get("volume", 0) or 0)
    vol_str = "$" + str(round(volume / 1000000, 1)) + "M"

    msg = (
        "🎯 <b>NEW PAPER TRADE</b>\n\n"
        "<b>Market:</b> " + trade["question"] + "\n\n"
        "<b>Pick:</b> " + trade["pick"] + "\n"
        "<b>Confidence:</b> " + str(trade["confidence"]) + "%\n"
        "<b>Edge:</b> +" + str(trade["edge"]) + "%\n"
        "<b>Paper Bet:</b> $" + str(trade["bet_size"]) + "\n"
        "<b>Potential Profit:</b> $" + str(trade["potential_profit"]) + "\n"
        "<b>Volume:</b> " + vol_str + "\n\n"
        "<b>Why:</b> " + trade["reasoning"] + "\n\n"
        "<b>Risk:</b> " + trade["risk_factors"]
    )
    return msg

def format_stats(data):
    stats = data["stats"]
    bankroll = data["bankroll"]
    profit = data["stats"]["profit"]
    win_rate = 0
    if stats["wins"] + stats["losses"] > 0:
        win_rate = round(stats["wins"] / (stats["wins"] + stats["losses"]) * 100, 1)

    msg = (
        "📊 <b>PAPER TRADING STATS</b>\n\n"
        "<b>Bankroll:</b> $" + str(round(bankroll, 2)) + "\n"
        "<b>Total P&L:</b> $" + str(round(profit, 2)) + "\n"
        "<b>Total Picks:</b> " + str(stats["total"]) + "\n"
        "<b>Wins:</b> " + str(stats["wins"]) + "\n"
        "<b>Losses:</b> " + str(stats["losses"]) + "\n"
        "<b>Pending:</b> " + str(stats["pending"]) + "\n"
        "<b>Win Rate:</b> " + str(win_rate) + "%\n"
        "<b>Peak Bankroll:</b> $" + str(round(stats.get("peak_bankroll", STARTING_BANKROLL), 2)) + "\n"
        "<b>Max Drawdown Limit:</b> " + str(int(DRAWDOWN_LIMIT * 100)) + "%\n"
        "<b>Daily Loss Limit:</b> " + str(int(DAILY_LOSS_LIMIT * 100)) + "%"
    )
    return msg

# Main Loop

def run_cycle(data):
    log.info("Starting research cycle...")
    picks_made = 0

    if not check_risk_limits(data):
        log.info("Risk limits hit, skipping cycle")
        return data

    markets = fetch_markets()
    if not markets:
        log.warning("No markets fetched")
        return data

    good_markets = filter_markets(markets)
    if not good_markets:
        log.warning("No markets passed filters")
        return data

    pending_ids = set(t["id"] for t in data["trades"] if t["status"] == "pending")

    for market in good_markets[:20]:
        market_id = market.get("id", "")

        if market_id in pending_ids:
            log.info("Already tracking: " + market.get("question", "")[:50])
            continue

        question = market.get("question", "")
        log.info("Researching: " + question[:60] + "...")

        research = research_market(market)

        if not research:
            log.warning("No research result for: " + question[:50])
            time.sleep(3)
            continue

        if research.get("skip"):
            log.info("Skipped (unreliable): " + question[:50])
            time.sleep(2)
            continue

        confidence = research.get("confidence", 0)
        edge = research.get("edge", 0)

        if confidence < MIN_CONFIDENCE:
            log.info("Low confidence (" + str(confidence) + "%), skipping: " + question[:50])
            time.sleep(2)
            continue

        if edge <= 0:
            log.info("No edge (" + str(edge) + "%), skipping: " + question[:50])
            time.sleep(2)
            continue

        trade = place_paper_trade(market, research, data)
        if trade:
            picks_made += 1
            msg = format_pick(trade, market)
            send_telegram(msg)
            log.info("Paper trade placed: " + question[:50])

        time.sleep(5)

    log.info("Cycle done. " + str(picks_made) + " new picks made.")

    if len(data["trades"]) > 0 and len(data["trades"]) % 5 == 0:
        send_telegram(format_stats(data))

    return data

def main():
    log.info("Polymarket Research Bot starting (Phase 1 - Paper Trading)")
    log.info("Starting bankroll: $" + str(STARTING_BANKROLL))
    log.info("Min confidence: " + str(MIN_CONFIDENCE) + "%")
    log.info("Poll interval: " + str(POLL_INTERVAL) + "s")
    log.info("Daily loss limit: " + str(int(DAILY_LOSS_LIMIT * 100)) + "%")
    log.info("Drawdown limit: " + str(int(DRAWDOWN_LIMIT * 100)) + "%")

    data = load_trades()
    log.info("Loaded " + str(len(data["trades"])) + " existing trades")

    send_telegram(
        "🤖 <b>Polymarket Bot Started</b>\n\n"
        "Phase 1: Paper Trading\n"
        "Starting Bankroll: $" + str(STARTING_BANKROLL) + "\n"
        "Min Confidence: " + str(MIN_CONFIDENCE) + "%\n"
        "Check Frequency: Every 20 mins\n"
        "Max Trade Duration: 7 days\n"
        "Daily Loss Limit: " + str(int(DAILY_LOSS_LIMIT * 100)) + "%\n"
        "Drawdown Limit: " + str(int(DRAWDOWN_LIMIT * 100)) + "%\n\n"
        "Monitoring markets..."
    )

    while True:
        try:
            data = run_cycle(data)
        except Exception as e:
            log.error("Cycle crashed: " + str(e))
        log.info("Sleeping " + str(POLL_INTERVAL) + "s...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
