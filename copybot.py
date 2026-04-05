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
POLL_INTERVAL     = 120           # check every 2 minutes
PAPER_TRADE_FILE  = "copy_trades.json"
STARTING_BANKROLL = 1000.0
DAILY_LOSS_LIMIT  = 0.05
DRAWDOWN_LIMIT    = 0.20
MAX_BET_PCT       = 0.05          # max 5% of bankroll per trade
COPY_RATIO        = 0.10          # bet 10% of what they bet proportionally
MAX_WALLETS       = 10
 
# Minimum requirements for a wallet to be tracked
MIN_WIN_RATE      = 0.58          # at least 58% win rate
MIN_TRADES        = 20            # at least 20 resolved trades
MIN_PROFIT        = 500           # at least $500 total profit
MIN_VOLUME        = 1000          # at least $1000 total volume
 
# Polymarket API endpoints
GAMMA_URL = "https://gamma-api.polymarket.com"
DATA_URL  = "https://data-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"
 
# Known profitable wallets to seed with (top public traders)
# These will be validated and more will be discovered automatically
SEED_WALLETS = [
    "0x1d0034134e4759b574d7a85a7d234f1f0a2df38c",  # from the tweet you shared
    "0x594edB9112f526Fa6A80b8F858A6379C8A2c1C11",
]
 
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
 
# Polymarket API
 
def get_wallet_stats(address):
    try:
        url = DATA_URL + "/profiles/" + address
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        log.warning("Profile fetch failed for " + address + ": " + str(e))
        return None
 
def get_wallet_positions(address):
    try:
        url = DATA_URL + "/positions"
        params = {"user": address, "limit": 100}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception as e:
        log.warning("Positions fetch failed: " + str(e))
        return []
 
def get_wallet_trades(address):
    try:
        url = DATA_URL + "/trades"
        params = {"maker": address, "limit": 100}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception as e:
        log.warning("Trades fetch failed: " + str(e))
        return []
 
def get_leaderboard():
    try:
        url = DATA_URL + "/leaderboard"
        params = {"limit": 50, "window": "all"}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        # Try alternative endpoint
        url2 = GAMMA_URL + "/leaderboard"
        r2 = requests.get(url2, params=params, timeout=15)
        if r2.status_code == 200:
            return r2.json()
        return []
    except Exception as e:
        log.warning("Leaderboard fetch failed: " + str(e))
        return []
 
def get_recent_trades_for_wallet(address):
    try:
        url = DATA_URL + "/trades"
        params = {"maker": address, "limit": 20}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("data", data.get("trades", []))
        return []
    except Exception as e:
        log.warning("Recent trades fetch failed: " + str(e))
        return []
 
# Wallet analysis
 
def analyze_wallet(address):
    log.info("  Analyzing wallet: " + address[:20] + "...")
 
    profile = get_wallet_stats(address)
    trades = get_wallet_trades(address)
 
    if not trades:
        log.info("  No trade history found")
        return None
 
    if isinstance(trades, dict):
        trades = trades.get("data", trades.get("trades", []))
 
    if len(trades) < MIN_TRADES:
        log.info("  Not enough trades: " + str(len(trades)))
        return None
 
    # Calculate stats from trades
    wins = 0
    losses = 0
    total_profit = 0.0
    total_volume = 0.0
 
    for trade in trades:
        size = float(trade.get("size", 0) or 0)
        price = float(trade.get("price", 0) or 0)
        side = trade.get("side", "").upper()
        total_volume += size * price
 
    # Try to get profit from profile
    profit = 0.0
    win_rate = 0.0
 
    if profile:
        profit = float(profile.get("profit", profile.get("pnl", 0)) or 0)
        win_rate_raw = profile.get("winRate", profile.get("win_rate", 0))
        if win_rate_raw:
            win_rate = float(win_rate_raw)
            if win_rate > 1:
                win_rate = win_rate / 100
 
    if total_volume < MIN_VOLUME:
        log.info("  Volume too low: $" + str(round(total_volume, 2)))
        return None
 
    if profit < MIN_PROFIT:
        log.info("  Profit too low: $" + str(round(profit, 2)))
        return None
 
    if win_rate < MIN_WIN_RATE and win_rate > 0:
        log.info("  Win rate too low: " + str(round(win_rate * 100, 1)) + "%")
        return None
 
    wallet_info = {
        "address": address,
        "profit": round(profit, 2),
        "win_rate": round(win_rate * 100, 1),
        "total_trades": len(trades),
        "total_volume": round(total_volume, 2),
        "last_checked": datetime.now().isoformat(),
        "last_trade_id": trades[0].get("id", "") if trades else ""
    }
 
    log.info("  GOOD WALLET: profit=$" + str(wallet_info["profit"]) + " winrate=" + str(wallet_info["win_rate"]) + "%")
    return wallet_info
 
def discover_wallets():
    log.info("Discovering profitable wallets...")
    good_wallets = []
 
    # Try leaderboard first
    leaderboard = get_leaderboard()
    addresses = []
 
    if leaderboard:
        if isinstance(leaderboard, list):
            for entry in leaderboard[:30]:
                addr = entry.get("address", entry.get("user", entry.get("proxyWallet", "")))
                if addr:
                    addresses.append(addr)
        log.info("Found " + str(len(addresses)) + " addresses from leaderboard")
 
    # Add seed wallets
    for addr in SEED_WALLETS:
        if addr not in addresses:
            addresses.append(addr)
 
    # Analyze each
    for address in addresses:
        if len(good_wallets) >= MAX_WALLETS:
            break
        try:
            wallet = analyze_wallet(address)
            if wallet:
                good_wallets.append(wallet)
            time.sleep(1)
        except Exception as e:
            log.warning("Error analyzing " + address[:20] + ": " + str(e))
 
    log.info("Found " + str(len(good_wallets)) + " qualifying wallets")
    return good_wallets
 
# Copy trading logic
 
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
            "Bankroll dropped " + str(round(drawdown * 100, 1)) + "% from peak\n"
            "Peak: $" + str(round(peak, 2)) + "\n"
            "Current: $" + str(round(bankroll, 2)) + "\n\n"
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
 
def calculate_copy_size(bankroll, their_bet_size):
    # Bet proportionally — 10% of what they bet relative to our bankroll
    raw = their_bet_size * COPY_RATIO
    max_bet = bankroll * MAX_BET_PCT
    return round(min(raw, max_bet), 2)
 
def check_wallet_for_new_trades(wallet, data):
    address = wallet["address"]
    last_trade_id = wallet.get("last_trade_id", "")
    new_trades = []
 
    recent = get_recent_trades_for_wallet(address)
    if not recent:
        return []
 
    for trade in recent:
        trade_id = str(trade.get("id", ""))
        if trade_id == last_trade_id:
            break
        new_trades.append(trade)
 
    if new_trades:
        wallet["last_trade_id"] = str(recent[0].get("id", ""))
        wallet["last_checked"] = datetime.now().isoformat()
        log.info("  Found " + str(len(new_trades)) + " new trades for " + address[:20])
 
    return new_trades
 
def place_copy_trade(wallet, original_trade, data):
    bankroll = data["bankroll"]
 
    their_size = float(original_trade.get("size", 0) or 0)
    their_price = float(original_trade.get("price", 0) or 0)
    their_bet = their_size * their_price
 
    if their_bet < 1:
        return None
 
    bet_size = calculate_copy_size(bankroll, their_bet)
    if bet_size < 0.50:
        return None
 
    outcome = original_trade.get("outcome", original_trade.get("side", "Unknown"))
    market_id = original_trade.get("market", original_trade.get("conditionId", "Unknown"))
    question = original_trade.get("title", original_trade.get("question", "Market " + str(market_id)[:20]))
 
    trade = {
        "id": str(original_trade.get("id", "")),
        "question": question,
        "market_id": str(market_id),
        "copied_from": wallet["address"],
        "copied_from_short": wallet["address"][:10] + "...",
        "wallet_win_rate": wallet["win_rate"],
        "wallet_profit": wallet["profit"],
        "pick": outcome,
        "their_bet": round(their_bet, 2),
        "their_price": their_price,
        "bet_size": bet_size,
        "potential_profit": round(bet_size * (1 - their_price) / their_price, 2) if their_price > 0 else 0,
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
    msg = (
        "📋 <b>COPY TRADE</b>\n\n"
        "📌 <b>Market:</b> " + trade["question"] + "\n\n"
        "✅ <b>Pick:</b> " + str(trade["pick"]) + "\n"
        "👛 <b>Copying:</b> " + trade["copied_from_short"] + "\n"
        "🏆 <b>Wallet Win Rate:</b> " + str(trade["wallet_win_rate"]) + "%\n"
        "💰 <b>Wallet Total Profit:</b> $" + str(trade["wallet_profit"]) + "\n\n"
        "📊 <b>Their Bet:</b> $" + str(trade["their_bet"]) + " @ " + str(round(trade["their_price"] * 100, 1)) + "¢\n"
        "💵 <b>Our Paper Bet:</b> $" + str(trade["bet_size"]) + "\n"
        "💸 <b>Potential Profit:</b> $" + str(trade["potential_profit"]) + "\n\n"
        "⏰ <b>Time:</b> " + trade["timestamp"][:16].replace("T", " ")
    )
    return msg
 
def format_stats(data):
    stats = data["stats"]
    win_rate = 0
    if stats["wins"] + stats["losses"] > 0:
        win_rate = round(stats["wins"] / (stats["wins"] + stats["losses"]) * 100, 1)
    return (
        "📊 <b>COPY TRADING STATS</b>\n\n"
        "<b>Bankroll:</b> $" + str(round(data["bankroll"], 2)) + "\n"
        "<b>Total P&L:</b> $" + str(round(stats["profit"], 2)) + "\n"
        "<b>Total Copies:</b> " + str(stats["total"]) + "\n"
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
        log.info("No wallets tracked yet, discovering...")
        wallets = discover_wallets()
        data["tracked_wallets"] = wallets
        save_data(data)
 
        if wallets:
            wallet_list = "\n".join([
                "👛 " + w["address"][:16] + "... | +" + str(w["profit"]) + " | " + str(w["win_rate"]) + "% WR"
                for w in wallets
            ])
            send_telegram(
                "🔍 <b>TRACKING " + str(len(wallets)) + " WALLETS</b>\n\n" + wallet_list
            )
        else:
            send_telegram("⚠️ No qualifying wallets found yet. Will retry next cycle.")
            return data
 
    # Check each wallet for new trades
    pending_ids = set(t["id"] for t in data["trades"] if t["status"] == "pending")
 
    for wallet in wallets:
        try:
            new_trades = check_wallet_for_new_trades(wallet, data)
            for trade in new_trades:
                trade_id = str(trade.get("id", ""))
                if trade_id in pending_ids:
                    continue
 
                copy = place_copy_trade(wallet, trade, data)
                if copy:
                    new_copies += 1
                    send_telegram(format_copy_trade(copy))
                    log.info("  Copied trade from " + wallet["address"][:16])
 
            time.sleep(1)
        except Exception as e:
            log.warning("Error checking wallet " + wallet["address"][:16] + ": " + str(e))
 
    # Refresh wallet list every 24 hours
    if wallets:
        last_checked = wallets[0].get("last_checked", "")
        if last_checked:
            try:
                last = datetime.fromisoformat(last_checked)
                if (datetime.now() - last).total_seconds() > 86400:
                    log.info("Refreshing wallet list...")
                    new_wallets = discover_wallets()
                    if new_wallets:
                        data["tracked_wallets"] = new_wallets
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
    log.info("Tracking up to " + str(MAX_WALLETS) + " wallets")
    log.info("Min win rate: " + str(int(MIN_WIN_RATE * 100)) + "%")
    log.info("Min profit: $" + str(MIN_PROFIT))
    log.info("Poll interval: " + str(POLL_INTERVAL) + "s")
 
    data = load_data()
    log.info("Loaded " + str(len(data["trades"])) + " existing trades")
    log.info("Tracking " + str(len(data.get("tracked_wallets", []))) + " wallets")
 
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
        "Scanning for winning wallets..."
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
