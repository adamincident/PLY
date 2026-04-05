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
POLL_INTERVAL     = 120
PAPER_TRADE_FILE  = "copy_trades.json"
STARTING_BANKROLL = 1000.0
DAILY_LOSS_LIMIT  = 0.05
DRAWDOWN_LIMIT    = 0.20
MAX_BET_PCT       = 0.05
COPY_RATIO        = 0.10
MAX_WALLETS       = 10
 
# Wallet quality filters
MIN_TRADES        = 10
MIN_PROFIT        = 500
 
DATA_URL  = "https://data-api.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
 
# Storage
 
def load_data():
    if os.path.exists(PAPER_TRADE_FILE):
        with open(PAPER_TRADE_FILE, "r") as f:
            return json.load(f)
    return {
        "bankroll": STARTING_BANKROLL,
        "tracked_wallets": [],
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
 
def save_data(data):
    with open(PAPER_TRADE_FILE, "w") as f:
        json.dump(data, f, indent=2)
 
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
 
# API helper
 
def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        log.warning("API " + url + " returned " + str(r.status_code))
        return None
    except Exception as e:
        log.warning("API error " + url + ": " + str(e))
        return None
 
# Leaderboard - returns list of {address, pnl, username}
 
def get_leaderboard():
    log.info("Fetching leaderboard...")
    entries = []
    seen = set()
 
    for period in ["ALL", "MONTH", "WEEK"]:
        result = safe_get(DATA_URL + "/v1/leaderboard", {
            "limit": 50,
            "timePeriod": period,
            "orderBy": "PNL"
        })
 
        if not result:
            continue
 
        if isinstance(result, dict):
            result = result.get("data", result.get("leaderboard", []))
 
        if not isinstance(result, list):
            continue
 
        for entry in result:
            addr = entry.get("proxyWallet") or entry.get("address", "")
            if not addr or addr in seen:
                continue
            seen.add(addr)
            pnl = float(entry.get("pnl", 0) or 0)
            username = entry.get("userName", "") or entry.get("xUsername", "")
            entries.append({
                "address": addr,
                "pnl": pnl,
                "username": username
            })
 
        time.sleep(0.5)
 
    log.info("Got " + str(len(entries)) + " unique addresses from leaderboard")
    return entries
 
# Wallet analysis - uses leaderboard PnL directly
 
def analyze_wallet(entry):
    address = entry["address"]
    pnl = entry["pnl"]
    username = entry.get("username", "")
 
    log.info("  Analyzing: " + address[:20] + "... pnl=$" + str(round(pnl, 2)))
 
    if pnl < MIN_PROFIT:
        log.info("  Skip: profit too low ($" + str(round(pnl, 2)) + ")")
        return None
 
    # Get recent trades to check activity and get last trade ID
    trades = safe_get(DATA_URL + "/trades", {"maker": address, "limit": 100})
    trade_count = 0
    last_trade_id = ""
 
    if trades:
        if isinstance(trades, dict):
            trades = trades.get("data", trades.get("trades", []))
        if isinstance(trades, list):
            trade_count = len(trades)
            if trades:
                last_trade_id = str(trades[0].get("id", ""))
 
    if trade_count < MIN_TRADES:
        log.info("  Skip: not enough trades (" + str(trade_count) + ")")
        return None
 
    log.info("  QUALIFIED: $" + str(round(pnl, 2)) + " profit, " + str(trade_count) + " trades")
 
    return {
        "address": address,
        "username": username,
        "profit": round(pnl, 2),
        "trade_count": trade_count,
        "last_trade_id": last_trade_id,
        "last_checked": datetime.now().isoformat()
    }
 
def discover_wallets():
    log.info("Discovering profitable wallets...")
    good_wallets = []
 
    leaderboard = get_leaderboard()
 
    if not leaderboard:
        log.warning("No leaderboard data")
        send_telegram("⚠️ Could not fetch leaderboard. Retrying next cycle.")
        return []
 
    # Sort by PnL descending so we analyze best first
    leaderboard.sort(key=lambda x: x["pnl"], reverse=True)
 
    for entry in leaderboard:
        if len(good_wallets) >= MAX_WALLETS:
            break
        try:
            wallet = analyze_wallet(entry)
            if wallet:
                good_wallets.append(wallet)
            time.sleep(1)
        except Exception as e:
            log.warning("Error analyzing " + entry["address"][:20] + ": " + str(e))
 
    log.info("Found " + str(len(good_wallets)) + " qualifying wallets")
    return good_wallets
 
# Risk management
 
def check_risk_limits(data):
    bankroll = data["bankroll"]
    peak = data["stats"].get("peak_bankroll", STARTING_BANKROLL)
 
    if bankroll > peak:
        data["stats"]["peak_bankroll"] = bankroll
        peak = bankroll
 
    drawdown = (peak - bankroll) / peak
    if drawdown >= DRAWDOWN_LIMIT:
        send_telegram(
            "🚨 <b>DRAWDOWN ALERT</b>\n\n"
            "Down " + str(round(drawdown * 100, 1)) + "% from peak\n"
            "Peak: $" + str(round(peak, 2)) + "\n"
            "Now: $" + str(round(bankroll, 2)) + "\n\n"
            "Bot paused."
        )
        return False
 
    today = datetime.now().strftime("%Y-%m-%d")
    daily_loss = sum(
        t.get("bet_size", 0)
        for t in data["trades"]
        if t.get("status") == "lost" and t.get("timestamp", "").startswith(today)
    )
    if daily_loss / STARTING_BANKROLL >= DAILY_LOSS_LIMIT:
        send_telegram(
            "⛔ <b>DAILY LOSS LIMIT HIT</b>\n\n"
            "Lost $" + str(round(daily_loss, 2)) + " today\n"
            "Resumes tomorrow."
        )
        return False
 
    return True
 
def calculate_copy_size(bankroll, their_bet):
    raw = their_bet * COPY_RATIO
    max_bet = bankroll * MAX_BET_PCT
    return round(min(raw, max_bet), 2)
 
def get_new_trades(wallet):
    address = wallet["address"]
    last_id = wallet.get("last_trade_id", "")
 
    recent = safe_get(DATA_URL + "/trades", {"maker": address, "limit": 10})
    if not recent:
        return []
 
    if isinstance(recent, dict):
        recent = recent.get("data", [])
    if not isinstance(recent, list):
        return []
 
    new_trades = []
    for trade in recent:
        trade_id = str(trade.get("id", ""))
        if trade_id == last_id:
            break
        new_trades.append(trade)
 
    if new_trades:
        wallet["last_trade_id"] = str(recent[0].get("id", ""))
        wallet["last_checked"] = datetime.now().isoformat()
        log.info("  " + str(len(new_trades)) + " new trades from " + address[:16])
 
    return new_trades
 
def place_copy_trade(wallet, original_trade, data):
    bankroll = data["bankroll"]
    size = float(original_trade.get("size", 0) or 0)
    price = float(original_trade.get("price", 0) or 0)
    their_bet = size * price
 
    if their_bet < 0.50:
        return None
 
    bet_size = calculate_copy_size(bankroll, their_bet)
    if bet_size < 0.25:
        return None
 
    outcome = original_trade.get("outcome", original_trade.get("side", "Unknown"))
    title = original_trade.get("title", "Unknown market")
    username = wallet.get("username", wallet["address"][:10] + "...")
 
    trade = {
        "id": str(original_trade.get("id", "")),
        "question": title,
        "copied_from": wallet["address"],
        "wallet_name": username if username else wallet["address"][:10] + "...",
        "wallet_profit": wallet["profit"],
        "pick": outcome,
        "side": str(original_trade.get("side", "BUY")).upper(),
        "their_bet": round(their_bet, 2),
        "their_price": round(price, 3),
        "bet_size": bet_size,
        "potential_profit": round(bet_size * (1 - price) / price, 2) if 0 < price < 1 else 0,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "result": None
    }
 
    data["trades"].append(trade)
    data["stats"]["total"] += 1
    data["stats"]["pending"] += 1
    save_data(data)
    return trade
 
def format_copy_trade(trade):
    return (
        "📋 <b>COPY TRADE</b>\n\n"
        "📌 <b>Market:</b> " + trade["question"] + "\n\n"
        "✅ <b>Pick:</b> " + str(trade["pick"]) + "\n"
        "📊 <b>Price:</b> " + str(round(trade["their_price"] * 100, 1)) + "¢\n\n"
        "👛 <b>Copying:</b> " + trade["wallet_name"] + "\n"
        "💰 <b>Wallet Total Profit:</b> $" + str(trade["wallet_profit"]) + "\n\n"
        "💵 <b>Their Bet:</b> $" + str(trade["their_bet"]) + "\n"
        "💸 <b>Our Paper Bet:</b> $" + str(trade["bet_size"]) + "\n"
        "📈 <b>Potential Profit:</b> $" + str(trade["potential_profit"]) + "\n\n"
        "⏰ " + trade["timestamp"][:16].replace("T", " ")
    )
 
def format_stats(data):
    stats = data["stats"]
    win_rate = 0
    if stats["wins"] + stats["losses"] > 0:
        win_rate = round(stats["wins"] / (stats["wins"] + stats["losses"]) * 100, 1)
    return (
        "📊 <b>COPY TRADING STATS</b>\n\n"
        "<b>Bankroll:</b> $" + str(round(data["bankroll"], 2)) + "\n"
        "<b>Total P&L:</b> $" + str(round(stats["profit"], 2)) + "\n"
        "<b>Copies Made:</b> " + str(stats["total"]) + "\n"
        "<b>Wins:</b> " + str(stats["wins"]) + "\n"
        "<b>Losses:</b> " + str(stats["losses"]) + "\n"
        "<b>Pending:</b> " + str(stats["pending"]) + "\n"
        "<b>Win Rate:</b> " + str(win_rate) + "%\n"
        "<b>Peak Bankroll:</b> $" + str(round(stats.get("peak_bankroll", STARTING_BANKROLL), 2))
    )
 
# Main loop
 
def run_cycle(data):
    log.info("Starting cycle...")
    new_copies = 0
 
    if not check_risk_limits(data):
        return data
 
    wallets = data.get("tracked_wallets", [])
 
    if not wallets:
        log.info("No wallets yet, discovering...")
        wallets = discover_wallets()
        data["tracked_wallets"] = wallets
        save_data(data)
 
        if wallets:
            lines = [
                "👛 " + (w.get("username") or w["address"][:16] + "...") +
                " | $" + str(w["profit"]) + " profit"
                for w in wallets
            ]
            send_telegram(
                "🔍 <b>TRACKING " + str(len(wallets)) + " WALLETS</b>\n\n" +
                "\n".join(lines)
            )
        else:
            send_telegram("⚠️ No qualifying wallets found. Retrying next cycle.")
            return data
 
    # Check each wallet for new trades
    pending_ids = set(t["id"] for t in data["trades"] if t["status"] == "pending")
 
    for wallet in wallets:
        try:
            new_trades = get_new_trades(wallet)
            for trade in new_trades:
                trade_id = str(trade.get("id", ""))
                if trade_id in pending_ids:
                    continue
                if str(trade.get("side", "")).upper() != "BUY":
                    continue
 
                copy = place_copy_trade(wallet, trade, data)
                if copy:
                    new_copies += 1
                    send_telegram(format_copy_trade(copy))
                    log.info("  Copied from " + wallet["address"][:16])
 
            time.sleep(1)
        except Exception as e:
            log.warning("Wallet check error " + wallet["address"][:16] + ": " + str(e))
 
    # Refresh wallet list every 6 hours
    if wallets:
        try:
            last = datetime.fromisoformat(wallets[0].get("last_checked", datetime.now().isoformat()))
            if (datetime.now() - last).total_seconds() > 21600:
                log.info("Refreshing wallet list...")
                fresh = discover_wallets()
                if fresh:
                    data["tracked_wallets"] = fresh
        except Exception:
            pass
 
    log.info("Cycle done. " + str(new_copies) + " new copies.")
 
    if data["stats"]["total"] > 0 and data["stats"]["total"] % 5 == 0:
        send_telegram(format_stats(data))
 
    save_data(data)
    return data
 
def main():
    log.info("Polymarket Copy Bot starting (Phase 1 - Paper Trading)")
    log.info("Bankroll: $" + str(STARTING_BANKROLL))
    log.info("Max wallets: " + str(MAX_WALLETS))
    log.info("Min profit: $" + str(MIN_PROFIT))
    log.info("Min trades: " + str(MIN_TRADES))
    log.info("Poll interval: " + str(POLL_INTERVAL) + "s")
 
    data = load_data()
    log.info("Loaded " + str(len(data["trades"])) + " trades, " +
             str(len(data.get("tracked_wallets", []))) + " wallets")
 
    send_telegram(
        "🤖 <b>Polymarket Copy Bot Started</b>\n\n"
        "Phase 1: Paper Trading\n"
        "Strategy: Copy top profitable wallets\n"
        "Bankroll: $" + str(STARTING_BANKROLL) + "\n"
        "Max Wallets: " + str(MAX_WALLETS) + "\n"
        "Min Profit: $" + str(MIN_PROFIT) + "\n"
        "Daily Loss Limit: " + str(int(DAILY_LOSS_LIMIT * 100)) + "%\n"
        "Drawdown Limit: " + str(int(DRAWDOWN_LIMIT * 100)) + "%\n\n"
        "Scanning leaderboard..."
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
