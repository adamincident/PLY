import requests
import time
import json
import os
import logging
from datetime import datetime, timezone
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)
 
# Config
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "")
CHAT_ID           = os.environ.get("CHAT_ID", "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "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")
NEWS_API_KEY      = os.environ.get("NEWS_API_KEY", "e3d90c1128f541f59ba60166c0b4d15b")
POLL_INTERVAL     = 1200
MIN_CONFIDENCE    = 65
MIN_VOLUME        = 5000
PAPER_TRADE_FILE  = "paper_trades.json"
DAILY_LOSS_LIMIT  = 0.05
DRAWDOWN_LIMIT    = 0.20
STARTING_BANKROLL = 1000.0
 
# Skip these market types - no real edge
SKIP_KEYWORDS = [
    "above $", "below $", "price of bitcoin", "price of eth",
    "price of solana", "btc price", "eth price",
    "vs.", "vs ", "match", "game", "score", "winner of",
    "championship", "tournament", "nba", "nfl", "nhl", "mlb",
    "premier league", "la liga", "serie a", "bundesliga",
    "counter-strike", "esport", "dota", "league of legends"
]
 
# Good market types we want
GOOD_KEYWORDS = [
    "federal reserve", "fed rate", "interest rate", "inflation",
    "election", "president", "minister", "congress", "senate",
    "will trump", "will biden", "will putin", "will xi",
    "tariff", "trade war", "sanction", "ban", "law", "bill",
    "recession", "gdp", "unemployment", "cpi",
    "sec", "regulation", "lawsuit", "fine", "arrest",
    "ceasefire", "war", "invasion", "treaty", "deal",
    "ipo", "merger", "acquisition", "bankruptcy",
    "bitcoin etf", "crypto regulation", "coinbase", "binance"
]
 
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
 
# Live data fetchers
 
def fetch_news(query):
    if not NEWS_API_KEY:
        return "No news API key configured."
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": 5,
            "language": "en",
            "apiKey": NEWS_API_KEY
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            articles = r.json().get("articles", [])
            if not articles:
                return "No recent news found."
            summaries = []
            for a in articles[:5]:
                title = a.get("title", "")
                desc = a.get("description", "")
                date = a.get("publishedAt", "")[:10]
                summaries.append(date + ": " + title + ". " + (desc or ""))
            return "\n".join(summaries)
        return "News fetch failed: " + str(r.status_code)
    except Exception as e:
        return "News fetch error: " + str(e)
 
def fetch_crypto_price(symbol):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": symbol,
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if symbol in data:
                price = data[symbol]["usd"]
                change = data[symbol].get("usd_24h_change", 0)
                return symbol + " price: $" + str(price) + " (24h: " + str(round(change, 2)) + "%)"
        return ""
    except Exception:
        return ""
 
def fetch_live_context(question):
    context_parts = []
 
    # Check if crypto related
    q_lower = question.lower()
    if "bitcoin" in q_lower or "btc" in q_lower:
        price = fetch_crypto_price("bitcoin")
        if price:
            context_parts.append(price)
    if "ethereum" in q_lower or "eth" in q_lower:
        price = fetch_crypto_price("ethereum")
        if price:
            context_parts.append(price)
    if "solana" in q_lower or "sol" in q_lower:
        price = fetch_crypto_price("solana")
        if price:
            context_parts.append(price)
 
    # Fetch news
    news = fetch_news(question[:100])
    if news:
        context_parts.append("Recent news:\n" + news)
 
    return "\n\n".join(context_parts) if context_parts else "No live data available."
 
# Polymarket API
 
def fetch_markets():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100,
        "order": "volume",
        "ascending": "false"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            markets = r.json()
            log.info("Fetched " + str(len(markets)) + " markets")
            return markets
        else:
            log.error("Polymarket API error: " + str(r.status_code))
            return []
    except Exception as e:
        log.error("Failed to fetch markets: " + str(e))
        return []
 
def get_end_date(market):
    for key in ["endDate", "endDateIso", "end_date", "endTs"]:
        val = market.get(key)
        if val:
            return val
    return None
 
def get_volume(market):
    for key in ["volume", "volume24hr", "volumeNum"]:
        val = market.get(key)
        if val is not None:
            try:
                return float(val)
            except Exception:
                pass
    return 0.0
 
def get_prices(market):
    for key in ["outcomePrices", "prices"]:
        val = market.get(key)
        if val:
            try:
                if isinstance(val, str):
                    return json.loads(val)
                return val
            except Exception:
                pass
    return []
 
def is_good_market(question):
    q_lower = question.lower()
 
    # Skip if matches skip keywords
    for kw in SKIP_KEYWORDS:
        if kw in q_lower:
            return False, "skip keyword: " + kw
 
    # Must match at least one good keyword
    for kw in GOOD_KEYWORDS:
        if kw in q_lower:
            return True, "good keyword: " + kw
 
    return False, "no good keyword match"
 
def filter_markets(markets):
    good = []
    skipped_volume = 0
    skipped_date = 0
    skipped_flip = 0
    skipped_type = 0
 
    for m in markets:
        try:
            if not m.get("question"):
                continue
 
            volume = get_volume(m)
            if volume < MIN_VOLUME:
                skipped_volume += 1
                continue
 
            end_date = get_end_date(m)
            if end_date:
                try:
                    if isinstance(end_date, (int, float)):
                        end = datetime.fromtimestamp(end_date, tz=timezone.utc)
                    else:
                        end_str = str(end_date).replace("Z", "+00:00")
                        end = datetime.fromisoformat(end_str)
                        if end.tzinfo is None:
                            end = end.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    hours_left = (end - now).total_seconds() / 3600
                    if hours_left < 1 or hours_left > 168:
                        skipped_date += 1
                        continue
                except Exception as e:
                    log.warning("Date parse error: " + str(e))
 
            price_list = get_prices(m)
            if len(price_list) == 2:
                try:
                    p1 = float(price_list[0])
                    p2 = float(price_list[1])
                    if 0.45 <= p1 <= 0.55 and 0.45 <= p2 <= 0.55:
                        skipped_flip += 1
                        continue
                except Exception:
                    pass
 
            ok, reason = is_good_market(m.get("question", ""))
            if not ok:
                skipped_type += 1
                continue
 
            good.append(m)
 
        except Exception as e:
            log.warning("Filter error: " + str(e))
            continue
 
    log.info("Filtered to " + str(len(good)) + " | skipped: vol=" + str(skipped_volume) + " date=" + str(skipped_date) + " flip=" + str(skipped_flip) + " type=" + str(skipped_type))
    return good
 
# Groq API (free)
 
def research_market(market):
    question = market.get("question", "")
    description = market.get("description", "")
    price_list = get_prices(market)
    outcomes = market.get("outcomes", "[]")
 
    try:
        outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    except Exception:
        outcome_list = []
 
    # Fetch live context
    log.info("  Fetching live data for: " + question[:50])
    live_context = fetch_live_context(question)
 
    # Build prompt
    context = "Question: " + question + "\n"
    if description:
        context += "Description: " + str(description)[:300] + "\n"
    if outcome_list and price_list:
        context += "Current market odds:\n"
        for i, outcome in enumerate(outcome_list):
            if i < len(price_list):
                try:
                    prob = float(price_list[i]) * 100
                    context += "  " + str(outcome) + ": " + str(round(prob, 1)) + "%\n"
                except Exception:
                    pass
 
    context += "\nLIVE DATA (use this, not your training data):\n" + live_context
 
    prompt = """You are an expert prediction market analyst. Use the LIVE DATA provided to analyze this Polymarket question. Do NOT rely on your training data for current facts - only use the live data provided.
 
""" + context + """
 
Based on the live data above, give your assessment.
 
Respond in this EXACT format (JSON only, no other text):
{
  "pick": "YES or NO or exact outcome name",
  "confidence": 75,
  "edge": 15,
  "reasoning": "2-3 sentences based on the live data provided",
  "risk_factors": "main thing that could make you wrong",
  "skip": false
}
 
If the live data is insufficient to make a confident call, set skip to true.
Confidence = your probability (0-100). Edge = your confidence minus market implied probability.
Make sure pick matches your reasoning - if reasoning says YES, pick must be YES."""
 
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + GROQ_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.1
            },
            timeout=30
        )
 
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
 
            # Sanity check - make sure pick matches reasoning
            pick = str(result.get("pick", "")).upper()
            reasoning = result.get("reasoning", "").lower()
            if pick == "NO" and ("extremely likely" in reasoning or "very likely yes" in reasoning):
                log.warning("  Pick/reasoning mismatch detected, skipping")
                result["skip"] = True
 
            return result
        else:
            log.error("Groq API error: " + str(r.status_code) + " " + r.text[:200])
            return None
 
    except json.JSONDecodeError as e:
        log.error("JSON parse error: " + str(e))
        return None
    except Exception as e:
        log.error("Research failed: " + str(e))
        return None
 
# Risk management
 
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
        log.warning("Drawdown limit hit")
        return False
 
    today = datetime.now().strftime("%Y-%m-%d")
    daily_loss = 0.0
    for t in data["trades"]:
        if t.get("status") == "lost" and t.get("timestamp", "").startswith(today):
            daily_loss += t.get("bet_size", 0)
 
    if daily_loss / STARTING_BANKROLL >= DAILY_LOSS_LIMIT:
        msg = (
            "⛔ DAILY LOSS LIMIT HIT\n\n"
            "Lost $" + str(round(daily_loss, 2)) + " today\n\n"
            "No more bets today. Resumes tomorrow."
        )
        send_telegram(msg)
        log.warning("Daily loss limit hit")
        return False
 
    return True
 
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
        "id": str(market.get("id", "unknown")),
        "question": market.get("question", ""),
        "pick": research["pick"],
        "confidence": confidence,
        "edge": edge,
        "reasoning": research["reasoning"],
        "risk_factors": research["risk_factors"],
        "bet_size": bet_size,
        "potential_profit": round(bet_size * (edge / 100), 2),
        "timestamp": datetime.now().isoformat(),
        "end_date": str(get_end_date(market) or ""),
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
        log.error("Telegram failed: " + str(e))
        return False
 
def format_pick(trade, market):
    volume = get_volume(market)
    vol_str = "$" + str(round(volume / 1000, 1)) + "K"
    end = str(trade.get("end_date", ""))[:10] or "Unknown"

    msg = (
        "🎯 <b>NEW PAPER TRADE</b>\n\n"
        "📋 <b>" + trade["question"] + "</b>\n\n"
        "✅ <b>Pick:</b> " + str(trade["pick"]) + "\n"
        "🎯 <b>Confidence:</b> " + str(trade["confidence"]) + "%\n"
        "📈 <b>Edge:</b> +" + str(trade["edge"]) + "%\n"
        "💵 <b>Paper Bet:</b> $" + str(trade["bet_size"]) + "\n"
        "💰 <b>Potential Profit:</b> $" + str(trade["potential_profit"]) + "\n"
        "📊 <b>Volume:</b> " + vol_str + "\n"
        "⏰ <b>Resolves:</b> " + end + "\n\n"
        "🧠 <b>Reasoning:</b>\n" + str(trade["reasoning"]) + "\n\n"
        "⚠️ <b>Risk:</b>\n" + str(trade["risk_factors"])
    )
    return msg
 
def format_stats(data):
    stats = data["stats"]
    win_rate = 0
    if stats["wins"] + stats["losses"] > 0:
        win_rate = round(stats["wins"] / (stats["wins"] + stats["losses"]) * 100, 1)
    msg = (
        "📊 <b>PAPER TRADING STATS</b>\n\n"
        "<b>Bankroll:</b> $" + str(round(data["bankroll"], 2)) + "\n"
        "<b>Total P&L:</b> $" + str(round(stats["profit"], 2)) + "\n"
        "<b>Total Picks:</b> " + str(stats["total"]) + "\n"
        "<b>Wins:</b> " + str(stats["wins"]) + "\n"
        "<b>Losses:</b> " + str(stats["losses"]) + "\n"
        "<b>Pending:</b> " + str(stats["pending"]) + "\n"
        "<b>Win Rate:</b> " + str(win_rate) + "%\n"
        "<b>Peak Bankroll:</b> $" + str(round(stats.get("peak_bankroll", STARTING_BANKROLL), 2))
    )
    return msg
 
# Main loop
 
def run_cycle(data):
    log.info("Starting cycle...")
    picks_made = 0
 
    if not check_risk_limits(data):
        return data
 
    markets = fetch_markets()
    if not markets:
        return data
 
    good_markets = filter_markets(markets)
    if not good_markets:
        log.info("No markets passed filters this cycle")
        return data
 
    pending_ids = set(t["id"] for t in data["trades"] if t["status"] == "pending")
 
    for market in good_markets[:15]:
        market_id = str(market.get("id", ""))
 
        if market_id in pending_ids:
            continue
 
        question = market.get("question", "")
        log.info("Researching: " + question[:60])
 
        research = research_market(market)
 
        if not research:
            time.sleep(3)
            continue
 
        if research.get("skip"):
            log.info("  Skipped (insufficient data)")
            time.sleep(2)
            continue
 
        confidence = research.get("confidence", 0)
        edge = research.get("edge", 0)
 
        if confidence < MIN_CONFIDENCE:
            log.info("  Low confidence: " + str(confidence) + "%")
            time.sleep(2)
            continue
 
        if edge <= 0:
            log.info("  No edge: " + str(edge) + "%")
            time.sleep(2)
            continue
 
        trade = place_paper_trade(market, research, data)
        if trade:
            picks_made += 1
            send_telegram(format_pick(trade, market))
            log.info("  Trade placed!")
 
        time.sleep(5)
 
    log.info("Cycle done. " + str(picks_made) + " new picks.")
 
    if data["stats"]["total"] > 0 and data["stats"]["total"] % 5 == 0:
        send_telegram(format_stats(data))
 
    return data
 
def main():
    log.info("Polymarket Bot starting (Phase 1 - Paper Trading)")
    log.info("Using: Groq (free) + NewsAPI + CoinGecko")
    log.info("Bankroll: $" + str(STARTING_BANKROLL))
    log.info("Min confidence: " + str(MIN_CONFIDENCE) + "%")
    log.info("Poll interval: " + str(POLL_INTERVAL) + "s")
 
    data = load_trades()
    log.info("Loaded " + str(len(data["trades"])) + " existing trades")
 
    send_telegram(
        "🤖 <b>Polymarket Bot Started</b>\n\n"
        "Phase 1: Paper Trading\n"
        "Engine: Groq AI + Live News\n"
        "Bankroll: $" + str(STARTING_BANKROLL) + "\n"
        "Min Confidence: " + str(MIN_CONFIDENCE) + "%\n"
        "Focus: Politics, Economics, Regulation\n"
        "Daily Loss Limit: " + str(int(DAILY_LOSS_LIMIT * 100)) + "%\n"
        "Drawdown Limit: " + str(int(DRAWDOWN_LIMIT * 100)) + "%"
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
