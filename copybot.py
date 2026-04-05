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
MIN_WIN_RATE      = 0.55
MIN_TRADES        = 10
MIN_PROFIT        = 200
 
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
 
# Polymarket API helpers
 
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
 
# Leaderboard - get top wallets by PnL
 
def get_leaderboard():
    log.info("Fetching leaderboard...")
    addresses = []
 
    # Try multiple periods to get more addresses
    for period in ["ALL", "MONTH", "WEEK"]:
        result = safe_get(DATA_URL + "/v1/leaderboard", {
            "limit": 50,
            "timePeriod": period,
            "orderBy": "PNL"
        })
        if result:
            if isinstance(result, list):
                entries = result
            elif isinstance(result, dict):
                entries = result.get("data", result.get("leaderboard", []))
            else:
                entries = []
 
            for entry in entries:
                addr = (
                    entry.get("proxyWallet") or
                    entry.get("address") or
                    entry.get("user") or
                    entry.get("proxy_wallet", "")
                )
                if addr and addr not in addresses:
                    addresses.append(addr)
 
        time.sleep(0.5)
 
    log.info("Got " + str(len(addresses)) + " addresses from leaderboard")
    return addresses
 
# Calculate wallet PnL from trades + activity
 
def calculate_wallet_pnl(address):
    total_invested = 0.0
    total_returned = 0.0
    trade_count = 0
    wins = 0
    losses = 0
 
    # Fetch trades
    trades = safe_get(DATA_URL + "/trades", {"maker": address, "limit": 100})
    if not trades:
        trades = safe_get(DATA_URL + "/activity", {"user": address, "type": "TRADE", "limit": 100})
 
    if trades:
        if isinstance(trades, dict):
            trades = trades.get("data", trades.get("trades", []))
        if isinstance(trades, list):
            for t in trades:
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                side = str(t.get("side", "")).upper()
                cost = size * price
                if side == "BUY":
                    total_invested += cost
                    trade_count += 1
                elif side == "SELL":
                    total_returned += cost
 
    # Fetch redemptions (actual winnings)
    activity = safe_get(DATA_URL + "/activity", {"user": address, "type": "REDEEM", "limit": 100})
    if activity:
        if isinstance(activity, dict):
            activity = activity.get("data", activity.get("activity", []))
        if isinstance(activity, list):
            for a in activity:
                val = float(a.get("value", 0) or a.get("amount", 0) or 0)
                total_returned += val
                wins += 1
 
    # Closed positions
    closed = safe_get(DATA_URL + "/closed-positions", {"user": address, "limit": 100})
    if closed:
        if isinstance(closed, dict):
            closed = closed.get("data", [])
        if isinstance(closed, list):
            for p in closed:
                cash_pnl = float(p.get("cashPnl", 0) or 0)
                if cash_pnl > 0:
                    wins += 1
                elif cash_pnl < 0:
                    losses += 1
 
    realized_pnl = total_returned - total_invested
    total_resolved = wins + losses
    win_rate = wins / total_resolved if total_resolved > 0 else 0
 
    return {
        "profit": round(realized_pnl, 2),
        "win_rate": round(win_rate, 3),
        "trade_count": trade_count,
        "wins": wins,
        "losses": losses
    }
 
def analyze_wallet(address):
    log.info("  Analyzing: " + address[:20] + "...")
 
    stats = calculate_wallet_pnl(address)
 
    log.info("  profit=$" + str(stats["profit"]) +
             " winrate=" + str(round(stats["win_rate"] * 100, 1)) + "%" +
             " trades=" + str(stats["trade_count"]))
 
    if stats["trade_count"] < MIN_TRADES:
        log.info("  Skip: not enough trades")
        return None
 
    if stats["profit"] < MIN_PROFIT:
        log.info("  Skip: profit too low")
        return None
 
    if stats["win_rate"] < MIN_WIN_RATE and stats["wins"] + stats["losses"] > 5:
        log.info("  Skip: win rate too low")
        return None
 
    # Get most recent trade ID for change detection
    last_trade_id = ""
    recent = safe_get(DATA_URL + "/trades", {"maker": address, "limit": 1})
    if recent:
        if isinstance(recent, dict):
            recent = recent.get("data", [])
        if isinstance(recent, list) and recent:
            last_trade_id = str(recent[0].get("id", ""))
 
    return {
        "address": address,
        "profit": stats["profit"],
        "win_rate": round(stats["win_rate"] * 100, 1),
        "trade_count": stats["trade_count"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "last_trade_id": last_trade_id,
        "last_checked": datetime.now().isoformat()
    }
 
def discover_wallets():
    log.info("Discovering profitable wallets...")
    good_wallets = []
 
    addresses = get_leaderboard()
 
    if not addresses:
        log.warning("No addresses from leaderboard, leaderboard API may be unavailable")
        send_telegram("⚠️ Could not fetch leaderboard. Will retry next cycle.")
        return []
 
    for address in addresses:
        if len(good_wallets) >= MAX_WALLETS:
            break
        try:
            wallet = analyze_wallet(address)
            if wallet:
                good_wallets.append(wallet)
                log.info("  ADDED: " + address[:20] + " profit=$" + str(wallet["profit"]))
            time.sleep(1)
        except Exception as e:
            log.warning("Error analyzing " + address[:20] + ": " + str(e))
 
    log.info("Found " + str(len(good_wallets)) + " qualifying wallets")
    return good_wallets
 
# Copy trade logic
 
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
 
    side = str(original_trade.get("side", "BUY")).upper()
    outcome = original_trade.get("outcome", side)
    title = original_trade.get("title", "Unknown market")
 
    trade = {
        "id": str(original_trade.get("id", "")),
        "question": title,
        "copied_from": wallet["address"],
        "wallet_short": wallet["address"][:10] + "...",
        "wallet_win_rate": wallet["win_rate"],
        "wallet_profit": wallet["profit"],
        "pick": outcome,
        "side": side,
        "their_bet": round(their_bet, 2),
        "their_price": round(price, 3),
        "bet_size": bet_size,
        "potential_profit": round(bet_size * (1 - price) / price, 2) if price > 0 and price < 1 else 0,
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
        "👛 <b>Copying:</b> " + trade["wallet_short"] + "\n"
        "🏆 <b>Win Rate:</b> " + str(trade["wallet_win_rate"]) + "%\n"
        "💰 <b>Their Total Profit:</b> $" + str(trade["wallet_profit"]) + "\n\n"
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
                "👛 " + w["address"][:16] + "... | $" + str(w["profit"]) + " profit | " + str(w["win_rate"]) + "% WR"
                for w in wallets
            ]
            send_telegram(
                "🔍 <b>TRACKING " + str(len(wallets)) + " WALLETS</b>\n\n" +
                "\n".join(lines)
            )
        else:
            send_telegram("⚠️ No qualifying wallets found yet. Retrying next cycle.")
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
                # Only copy BUY trades
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
    log.info("Min win rate: " + str(int(MIN_WIN_RATE * 100)) + "%")
    log.info("Min profit: $" + str(MIN_PROFIT))
    log.info("Poll interval: " + str(POLL_INTERVAL) + "s")
 
    data = load_data()
    log.info("Loaded " + str(len(data["trades"])) + " trades, " + str(len(data.get("tracked_wallets", []))) + " wallets")
 
    send_telegram(
        "🤖 <b>Polymarket Copy Bot Started</b>\n\n"
        "Phase 1: Paper Trading\n"
        "Strategy: Copy top profitable wallets\n"
        "Bankroll: $" + str(STARTING_BANKROLL) + "\n"
        "Max Wallets: " + str(MAX_WALLETS) + "\n"
        "Min Win Rate: " + str(int(MIN_WIN_RATE * 100)) + "%\n"
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
