import os
import telebot
import yfinance as yf
import pandas as pd
import numpy as np
import threading
import time
import requests
import csv
from flask import Flask
from datetime import datetime
import pytz

# NEW: Position tracking imports
from position_tracker import PositionTracker
from config import get_telegram_token, get_telegram_chat_id

# ==========================================
# 🔐 SECURE CONFIGURATION (from environment variables)
# ==========================================
print("\n🔐 Loading credentials securely...")
API_TOKEN = get_telegram_token()
YOUR_CHAT_ID = get_telegram_chat_id()
print("✅ All credentials loaded from environment\n")
# ==========================================

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# NEW: Initialize position tracker
position_tracker = PositionTracker()

# ==========================================
# ULTIMATE HYBRID: SHARES EXECUTION + OPTIONS INSIGHTS + POSITION TRACKING
# Trades shares (proven 89% return)
# Shows options for manual consideration
# Tracks all positions with stop/target alerts
# ==========================================

def log_trade_to_csv(trade_data):
    """Log every alert"""
    file_exists = os.path.isfile('live_trades.csv')
    with open('live_trades.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=trade_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)

def get_sp300_tickers():
    """Get S&P 500 top 300 (cached)"""
    try:
        cache_file = 'sp300_cache.txt'
        if os.path.exists(cache_file):
            mod_time = os.path.getmtime(cache_file)
            if time.time() - mod_time < 86400:
                with open(cache_file, 'r') as f:
                    return f.read().strip().split(',')
        
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        tickers = [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
        sp300 = tickers[:300]
        
        with open(cache_file, 'w') as f:
            f.write(','.join(sp300))
        
        return sp300
    except:
        return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", 
                "AMD", "NFLX", "SPY", "QQQ"]

def get_yahoo_top_movers():
    """Yahoo most active top 30"""
    try:
        url = "https://finance.yahoo.com/most-active"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            df = pd.read_html(r.text)[0]
            movers = [t for t in df['Symbol'].tolist() if "-" not in t and len(t) < 6]
            return movers[:30]
    except:
        pass
    return []

def get_scan_tickers():
    """Combined S&P 300 + Yahoo top 30"""
    sp300 = get_sp300_tickers()
    movers = get_yahoo_top_movers()
    all_tickers = list(set(sp300 + movers))
    return all_tickers

# ==========================================
# INDICATORS (PROVEN FROM SHARES BACKTEST)
# ==========================================
def calculate_indicators(df):
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA200'] = df['Close'].rolling(200).mean()
    df['EMA20'] = df['Close'].ewm(span=20).mean()
    
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + gain / loss))
    
    high_low = df['High'] - df['Low']
    ranges = pd.concat([high_low, abs(df['High'] - df['Close'].shift()), 
                       abs(df['Low'] - df['Close'].shift())], axis=1)
    df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
    
    plus_dm = df['High'].diff()
    minus_dm = -df['Low'].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    
    atr_safe = df['ATR'].replace(0, np.nan)
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr_safe)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr_safe)
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['ADX'] = dx.rolling(14).mean()
    df['Plus_DI'] = plus_di
    df['Minus_DI'] = minus_di
    
    df['BB_Mid'] = df['Close'].rolling(20).mean()
    df['BB_Std'] = df['Close'].rolling(20).std()
    df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    bb_range = (df['BB_Upper'] - df['BB_Lower']).replace(0, np.nan)
    df['BB_Position'] = (df['Close'] - df['BB_Lower']) / bb_range
    
    df['Vol_Avg'] = df['Volume'].rolling(20).mean()
    df['Vol_Ratio'] = df['Volume'] / df['Vol_Avg']
    df['ROC_5'] = ((df['Close'] - df['Close'].shift(5)) / df['Close'].shift(5)) * 100
    
    return df

# ==========================================
# SCORING (PROVEN THRESHOLDS: 65/40/20)
# ==========================================
def calculate_scores(row):
    """Returns bull_score, bear_score, bear_confirms, reasons"""
    bull = 50
    bull_reasons = []
    
    # Trend
    if row['Close'] > row['SMA50'] > row['SMA200']:
        bull += 15
        bull_reasons.append("Strong Uptrend")
    elif row['Close'] > row['SMA50']:
        bull += 10
        bull_reasons.append("Above SMA50")
    elif row['Close'] > row['EMA20']:
        bull += 5
    
    if row['ADX'] > 25:
        bull += 10
        bull_reasons.append(f"ADX Strong ({row['ADX']:.0f})")
    elif row['ADX'] > 20:
        bull += 5
    
    if row['Plus_DI'] > row['Minus_DI'] + 5:
        bull += 5
        bull_reasons.append("Bullish Momentum")
    
    # RSI
    if row['RSI'] < 30:
        bull += 20
        bull_reasons.append(f"Oversold (RSI {row['RSI']:.0f})")
    elif row['RSI'] < 40:
        bull += 12
        bull_reasons.append(f"RSI Favorable ({row['RSI']:.0f})")
    elif row['RSI'] > 60:
        bull -= 8
    
    if row['ROC_5'] > 2:
        bull += 5
        bull_reasons.append("Positive Momentum")
    
    # Bollinger
    if row['BB_Position'] < 0.2:
        bull += 10
        bull_reasons.append("BB Oversold")
    elif row['BB_Position'] < 0.4:
        bull += 5
    
    # Volume
    if row['Vol_Ratio'] > 1.5:
        bull += 8
        bull_reasons.append(f"High Volume ({row['Vol_Ratio']:.1f}x)")
    elif row['Vol_Ratio'] > 1.2:
        bull += 4
    
    # Bear
    bear = 50
    confirms = 0
    bear_reasons = []
    
    if row['Close'] < row['SMA50']:
        bear -= 12
        confirms += 1
        bear_reasons.append("Below SMA50")
    
    if row['ADX'] > 25:
        bear -= 8
        confirms += 1
        bear_reasons.append(f"Strong Trend (ADX {row['ADX']:.0f})")
    
    if row['Minus_DI'] > row['Plus_DI'] + 10:
        bear -= 10
        confirms += 1
        bear_reasons.append("Bearish Momentum")
    
    if row['RSI'] > 70:
        bear -= 15
        confirms += 1
        bear_reasons.append(f"Overbought (RSI {row['RSI']:.0f})")
    
    if row['BB_Position'] > 0.9:
        bear -= 10
        confirms += 1
        bear_reasons.append("BB Overbought")
    
    if row['Vol_Ratio'] > 2.0:
        bear -= 12
        confirms += 1
        bear_reasons.append(f"High Volume ({row['Vol_Ratio']:.1f}x)")
    
    if confirms < 3:
        bear += 15
    
    bull = max(0, min(100, bull))
    bear = max(0, min(100, bear))
    
    return bull, bear, confirms, bull_reasons, bear_reasons

# ==========================================
# OPTIONS INSIGHTS (NOT FOR EXECUTION, JUST INFO)
# ==========================================
def get_option_insights(ticker, direction, atr, current_price):
    """Get options details for user information"""
    try:
        stock = yf.Ticker(ticker)
        exps = stock.options
        if not exps:
            return None
        
        today = datetime.now()
        target_dte = 45
        best_expiry = None
        
        valid = {}
        for e in exps:
            try:
                edate = datetime.strptime(e, "%Y-%m-%d")
                days = (edate - today).days
                if 30 <= days <= 60:
                    valid[e] = abs(days - target_dte)
            except:
                pass
        
        if not valid:
            return None
        
        best_expiry = min(valid, key=valid.get)
        expiry_date = datetime.strptime(best_expiry, "%Y-%m-%d")
        dte = (expiry_date - today).days
        
        move = atr * 1.5
        target_strike = current_price + move if direction == "CALL" else current_price - move
        
        opt = stock.option_chain(best_expiry)
        chain = opt.calls if direction == "CALL" else opt.puts
        
        chain = chain[(chain['openInterest'] > 50) | (chain['volume'] > 10)]
        
        if chain.empty:
            return None
        
        chain['diff'] = abs(chain['strike'] - target_strike)
        best = chain.sort_values('diff').iloc[0]
        
        spread = best['ask'] - best['bid']
        spread_pct = (spread / best['lastPrice'] * 100) if best['lastPrice'] > 0 else 999
        
        if spread_pct > 25:
            return None
        
        return {
            "type": direction,
            "strike": best['strike'],
            "expiry": best_expiry,
            "dte": dte,
            "last_price": best['lastPrice'],
            "bid": best['bid'],
            "ask": best['ask'],
            "volume": int(best['volume']),
            "oi": int(best['openInterest']),
            "spread_pct": spread_pct,
            "contracts_1k": int(1000 / (best['lastPrice'] * 100)),
            "contracts_2.5k": int(2500 / (best['lastPrice'] * 100))
        }
    
    except Exception as e:
        return None

# ==========================================
# MAIN ANALYSIS
# ==========================================
def analyze_stock(ticker, strict=True):
    """Analyze stock and return signal data"""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="2y")
        
        if len(df) < 250:
            return None
        
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        
        if pd.isna(latest['RSI']) or pd.isna(latest['ADX']) or pd.isna(latest['ATR']):
            return None
        
        bull, bear, confirms, bull_reasons, bear_reasons = calculate_scores(latest)
        
        direction = None
        reasons = []
        shares_stop = 0
        shares_target = 0
        
        if bull >= 65 and latest['ADX'] > 20:
            direction = "BULL"
            reasons = bull_reasons
            shares_stop = latest['Close'] - (latest['ATR'] * 2.5)
            shares_target = latest['Close'] + (latest['ATR'] * 3.5)
        
        elif bear <= 40 and confirms >= 3:
            direction = "BEAR"
            reasons = bear_reasons
            shares_stop = latest['Close'] + (latest['ATR'] * 2.0)
            shares_target = latest['Close'] - (latest['ATR'] * 4.0)
        
        if not strict and not direction:
            return {
                "ticker": ticker,
                "price": round(latest['Close'], 2),
                "direction": "NEUTRAL",
                "score": int(bull),
                "reasons": ["No setup found"],
                "shares_trade": None,
                "options_insight": None
            }
        
        if direction:
            position_size_10pct = 2500
            shares = int(position_size_10pct / latest['Close'])
            
            shares_trade = {
                "action": "BUY" if direction == "BULL" else "SHORT",
                "shares": shares,
                "price": latest['Close'],
                "capital": shares * latest['Close'],
                "stop": shares_stop,
                "target": shares_target,
                "risk_pct": abs((shares_stop - latest['Close']) / latest['Close'] * 100),
                "reward_pct": abs((shares_target - latest['Close']) / latest['Close'] * 100)
            }
            
            opt_type = "CALL" if direction == "BULL" else "PUT"
            options_insight = get_option_insights(ticker, opt_type, latest['ATR'], latest['Close'])
            
            return {
                "ticker": ticker,
                "price": round(latest['Close'], 2),
                "direction": direction,
                "score": int(bull if direction == "BULL" else (100 - bear)),
                "reasons": reasons,
                "atr": latest['ATR'],
                "adx": latest['ADX'],
                "rsi": latest['RSI'],
                "shares_trade": shares_trade,
                "options_insight": options_insight
            }
    
    except Exception as e:
        return None
    
    return None

# ==========================================
# MESSAGE FORMATTER
# ==========================================
def generate_alert_message(data):
    """Beautiful formatted alert"""
    if data['direction'] == "NEUTRAL":
        return f"⚖️ **{data['ticker']} NEUTRAL**\nScore: {data['score']}\n{data['reasons'][0]}"
    
    if data['score'] >= 80:
        strength = "🔥 VERY STRONG"
        stars = "⭐⭐⭐⭐⭐"
    elif data['score'] >= 75:
        strength = "💪 STRONG"
        stars = "⭐⭐⭐⭐"
    elif data['score'] >= 70:
        strength = "⚡ GOOD"
        stars = "⭐⭐⭐"
    else:
        strength = "📊 MODERATE"
        stars = "⭐⭐"
    
    icon = "🚀" if data['direction'] == "BULL" else "🐻"
    color = "🟢" if data['direction'] == "BULL" else "🔴"
    
    reasons = "\n".join([f"• {r}" for r in data['reasons'][:4]])
    
    st = data['shares_trade']
    
    shares_section = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 **SHARES TRADE** (Recommended):\n"
        f"  {st['action']}: {st['shares']} shares @ ${data['price']:.2f}\n"
        f"  💰 Capital: ${st['capital']:,.0f} (10% position)\n"
        f"  🛑 Stop: ${st['stop']:.2f} (-{st['risk_pct']:.1f}%)\n"
        f"  🎯 Target: ${st['target']:.2f} (+{st['reward_pct']:.1f}%)\n"
        f"  📊 Risk/Reward: 1:{st['reward_pct']/st['risk_pct']:.1f}\n"
        f"\n🤖 Position tracked! Exit alerts enabled."
    )
    
    opt = data['options_insight']
    if opt:
        if opt['dte'] > 50:
            dte_warning = "⚠️ Long DTE (slower theta)"
        elif opt['dte'] < 35:
            dte_warning = "⏰ Short DTE (faster theta)"
        else:
            dte_warning = f"✅ Optimal {opt['dte']} days"
        
        if opt['volume'] > 500 and opt['oi'] > 1000:
            liq_status = "✅ High Liquidity"
        elif opt['volume'] > 100 and opt['oi'] > 500:
            liq_status = "⚠️ Moderate Liquidity"
        else:
            liq_status = "🚨 Low Liquidity"
        
        options_section = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ **OPTIONS PLAY** (Alternative):\n"
            f"  {opt['type']} ${opt['strike']} exp {opt['expiry']}\n"
            f"  💰 Premium: ${opt['last_price']:.2f} (Bid: ${opt['bid']:.2f} / Ask: ${opt['ask']:.2f})\n"
            f"  📊 Vol: {opt['volume']:,} | OI: {opt['oi']:,}\n"
            f"  📈 Spread: {opt['spread_pct']:.1f}% {liq_status}\n"
            f"  🕐 {dte_warning}\n"
            f"  💵 Suggested: {opt['contracts_1k']}-{opt['contracts_2.5k']} contracts\n"
            f"\n"
            f"  🎯 Exit: 50% gain OR 15 days\n"
            f"  🛑 Stop: -30% loss"
        )
        
        recommendation = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 **RECOMMENDATION**:\n"
            f"  ✅ Shares: Proven 89% annual return, low risk\n"
            f"  ⚡ Options: Only if you expect 3-5 day explosive move"
        )
    else:
        options_section = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ **OPTIONS PLAY**: Not Available\n"
            f"  • No liquid options found"
        )
        recommendation = ""
    
    return (
        f"{icon} **{strength} {data['direction']}** {color}\n"
        f"**{data['ticker']}** @ ${data['price']:.2f}\n"
        f"Score: {data['score']}/100 {stars}\n"
        f"ADX: {data['adx']:.0f} | RSI: {data['rsi']:.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**📊 Why:**\n{reasons}\n\n"
        f"{shares_section}\n\n"
        f"{options_section}\n"
        f"{recommendation}"
    )

# ==========================================
# NEW: EXIT ALERT FUNCTIONS
# ==========================================
def check_position_exits():
    """Check if any positions hit stop/target"""
    try:
        open_positions = position_tracker.sheets.get_open_positions()
        
        if not open_positions:
            return
        
        current_prices = {}
        
        for pos in open_positions:
            ticker = pos['Ticker']
            if ticker not in current_prices:
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period='1d')
                    
                    if not hist.empty:
                        current_prices[ticker] = {
                            'current': float(hist['Close'].iloc[-1]),
                            'high': float(hist['High'].iloc[-1]),
                            'low': float(hist['Low'].iloc[-1])
                        }
                except:
                    continue
        
        exits = position_tracker.check_exits(current_prices)
        
        if exits:
            exit_alerts = position_tracker.process_exits(exits)
            
            for alert in exit_alerts:
                send_exit_alert(alert)
    
    except Exception as e:
        print(f"❌ Error checking exits: {e}")

def send_exit_alert(exit_data):
    """Send Telegram alert for position exit"""
    icon = "🎯" if exit_data['reason'] == 'TARGET' else "🛑"
    status = "TARGET HIT!" if exit_data['reason'] == 'TARGET' else "STOP HIT"
    color = "🟢" if exit_data['pnl']['dollar'] > 0 else "🔴"
    
    msg = f"""
{icon} **{status}** {color}
**{exit_data['ticker']}** {exit_data['direction']} {exit_data['type']}

📊 Trade Summary:
Entry: ${exit_data['entry']:.2f}
Exit: ${exit_data['exit']:.2f}

💰 P&L: ${exit_data['pnl']['dollar']:+,.2f} ({exit_data['pnl']['percent']:+.1f}%)

Shares: {int(exit_data['quantity'])}
Reason: {exit_data['reason']}

✅ Check Google Sheet for full details!
"""
    
    try:
        bot.send_message(YOUR_CHAT_ID, msg, parse_mode="Markdown")
        print(f"  📤 Exit alert sent: {exit_data['ticker']} {exit_data['pnl']['dollar']:+.2f}")
    except Exception as e:
        print(f"  ❌ Failed to send exit alert: {e}")

# ==========================================
# TELEGRAM COMMANDS
# ==========================================
@bot.message_handler(commands=['check'])
def manual_check(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return bot.reply_to(message, "⚠️ Use: /check TICKER\nExample: /check NVDA")
        
        ticker = parts[1].upper()
        bot.reply_to(message, f"🔍 Analyzing {ticker}...")
        
        data = analyze_stock(ticker, strict=False)
        
        if data:
            bot.send_message(message.chat.id, generate_alert_message(data), parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ Error analyzing ticker.")
    
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['scan'])
def manual_scan(message):
    bot.reply_to(message, "🦅 Force-scanning top movers...")
    movers = get_yahoo_top_movers()[:20]
    found = 0
    
    for ticker in movers:
        data = analyze_stock(ticker, strict=True)
        if data:
            bot.send_message(message.chat.id, generate_alert_message(data), parse_mode="Markdown")
            found += 1
            time.sleep(1)
    
    if found == 0:
        bot.reply_to(message, "😴 No setups in top movers.")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    try:
        if not os.path.isfile('live_trades.csv'):
            return bot.reply_to(message, "📊 No trades logged yet.")
        
        df = pd.read_csv('live_trades.csv')
        total = len(df)
        bulls = len(df[df['Direction'] == 'BULL'])
        bears = len(df[df['Direction'] == 'BEAR'])
        
        msg = (
            f"📊 **LIVE STATS**\n"
            f"Total Alerts: {total}\n"
            f"🐂 Bulls: {bulls}\n"
            f"🐻 Bears: {bears}\n"
            f"Latest: {df['Ticker'].iloc[-1]} ({df['Direction'].iloc[-1]})"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['positions'])
def show_positions(message):
    """NEW: Show all open positions"""
    try:
        open_positions = position_tracker.sheets.get_open_positions()
        
        if not open_positions:
            bot.reply_to(message, "📊 No open positions")
            return
        
        msg = f"📊 **OPEN POSITIONS ({len(open_positions)})**\n\n"
        
        for pos in open_positions:
            msg += f"**{pos['Ticker']}** {pos['Direction']} {pos['Type']}\n"
            msg += f"  Entry: ${pos['Entry_Price']}\n"
            msg += f"  Stop: ${pos['Stop']} | Target: ${pos['Target']}\n"
            msg += f"  Date: {pos['Entry_Date']}\n\n"
        
        bot.reply_to(message, msg, parse_mode="Markdown")
    
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

#==========================================
#COMMANDS
# ==========================================
# ADD THESE COMMAND HANDLERS TO YOUR BOT

# After the existing commands, add these:

@bot.message_handler(commands=['entered'])
def entered_from_alert(message):
    """User entered a trade from bot alert"""
    global last_activity_time
    last_activity_time = datetime.now()
    
    try:
        parts = message.text.split()
        
        # /entered ALERT_ID shares PRICE
        # /entered ALERT_ID options CONTRACTS PREMIUM
        
        if len(parts) < 4:
            bot.reply_to(message, 
                "⚠️ **Usage:**\n\n"
                "Shares: `/entered ALERT_ID shares PRICE`\n"
                "Example: `/entered abc123 shares 915`\n\n"
                "Options: `/entered ALERT_ID options CONTRACTS PREMIUM`\n"
                "Example: `/entered abc123 options 2 36.50`",
                parse_mode="Markdown")
            return
        
        alert_id = parts[1]
        trade_type_input = parts[2].upper()
        
        if trade_type_input == 'SHARES':
            entry_price = float(parts[3])
            quantity = position_tracker.alert_metadata.get(alert_id, {}).get('shares', 27)
            
            position_id, error = position_tracker.track_user_entry_from_alert(
                alert_id, entry_price, quantity, 'SHARES'
            )
            
            if error:
                bot.reply_to(message, f"❌ {error}")
                return
            
            metadata = position_tracker.alert_metadata[alert_id]
            atr_estimate = abs(metadata['target'] - metadata['price']) / 3.5
            
            if metadata['direction'] == 'BULL':
                stop = entry_price - (atr_estimate * 2.5)
                target = entry_price + (atr_estimate * 3.5)
            else:
                stop = entry_price + (atr_estimate * 2.0)
                target = entry_price - (atr_estimate * 4.0)
            
            msg = (
                f"✅ **Position Tracked!**\n\n"
                f"**{metadata['ticker']}** {metadata['direction']} SHARES\n"
                f"Entry: ${entry_price:.2f}\n"
                f"Shares: {quantity}\n"
                f"Stop: ${stop:.2f}\n"
                f"Target: ${target:.2f}\n\n"
                f"📊 Tracked in:\n"
                f"  ✅ Bot_Alerts (bot's price: ${metadata['price']:.2f})\n"
                f"  ✅ My_Trades (your price: ${entry_price:.2f})\n\n"
                f"🔔 I'll alert you when stop/target hit!"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        
        elif trade_type_input == 'OPTIONS':
            contracts = int(parts[3])
            premium = float(parts[4])
            
            position_id, error = position_tracker.track_user_entry_from_alert(
                alert_id, premium, contracts, 'CALL', premium
            )
            
            if error:
                bot.reply_to(message, f"❌ {error}")
                return
            
            metadata = position_tracker.alert_metadata[alert_id]
            stop = premium * 0.7
            target = premium * 1.5
            
            msg = (
                f"✅ **Options Position Tracked!**\n\n"
                f"**{metadata['ticker']}** {metadata['direction']} OPTIONS\n"
                f"Contracts: {contracts}\n"
                f"Premium: ${premium:.2f}\n"
                f"Stop: ${stop:.2f} (-30%)\n"
                f"Target: ${target:.2f} (+50%)\n\n"
                f"📊 Tracked in My_Trades\n\n"
                f"🔔 I'll alert you on exit!"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
    
    except ValueError:
        bot.reply_to(message, "❌ Invalid numbers. Check your command format.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['buy'])
def manual_buy(message):
    """User found their own trade"""
    global last_activity_time
    last_activity_time = datetime.now()
    
    try:
        parts = message.text.split()
        
        # /buy TICKER shares PRICE stop STOP target TARGET
        # /buy TICKER call/put STRIKE EXPIRY CONTRACTS PREMIUM
        
        if len(parts) < 5:
            bot.reply_to(message,
                "⚠️ **Usage:**\n\n"
                "Shares: `/buy TICKER shares PRICE stop STOP target TARGET`\n"
                "Example: `/buy AAPL shares 185 stop 180 target 195`\n\n"
                "Options: `/buy TICKER call/put STRIKE EXPIRY CONTRACTS PREMIUM`\n"
                "Example: `/buy NVDA call 920 2026-03-21 2 36.50`",
                parse_mode="Markdown")
            return
        
        ticker = parts[1].upper()
        trade_type_input = parts[2].lower()
        
        if trade_type_input == 'shares':
            entry_price = float(parts[3])
            
            # Find stop and target
            stop_idx = parts.index('stop') if 'stop' in parts else None
            target_idx = parts.index('target') if 'target' in parts else None
            
            if not stop_idx or not target_idx:
                bot.reply_to(message, "❌ Missing 'stop' or 'target' keyword")
                return
            
            stop = float(parts[stop_idx + 1])
            target = float(parts[target_idx + 1])
            
            # Determine direction
            if target > entry_price:
                direction = 'BULL'
            else:
                direction = 'BEAR'
            
            # Estimate quantity
            quantity = int(2500 / entry_price)
            
            position_id = position_tracker.track_manual_trade(
                ticker, direction, 'SHARES', entry_price, stop, target, quantity
            )
            
            msg = (
                f"✅ **Manual Trade Tracked!**\n\n"
                f"**{ticker}** {direction} SHARES\n"
                f"Entry: ${entry_price:.2f}\n"
                f"Shares: {quantity}\n"
                f"Stop: ${stop:.2f}\n"
                f"Target: ${target:.2f}\n\n"
                f"📊 Tracked in My_Trades ONLY\n"
                f"(Not in Bot_Alerts - you found this!)\n\n"
                f"🔔 I'll alert you on exit!"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        
        elif trade_type_input in ['call', 'put']:
            strike = float(parts[3])
            expiry = parts[4]
            contracts = int(parts[5])
            premium = float(parts[6])
            
            trade_type = 'CALL' if trade_type_input == 'call' else 'PUT'
            direction = 'BULL' if trade_type == 'CALL' else 'BEAR'
            
            stop = premium * 0.7
            target = premium * 1.5
            
            position_id = position_tracker.track_manual_trade(
                ticker, direction, trade_type, premium, stop, target, contracts,
                strike=strike, expiry=expiry, premium=premium
            )
            
            msg = (
                f"✅ **Manual Options Trade Tracked!**\n\n"
                f"**{ticker}** {trade_type} ${strike} exp {expiry}\n"
                f"Contracts: {contracts}\n"
                f"Premium: ${premium:.2f}\n"
                f"Stop: ${stop:.2f}\n"
                f"Target: ${target:.2f}\n\n"
                f"📊 Tracked in My_Trades ONLY\n\n"
                f"🔔 I'll alert you on exit!"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
    
    except ValueError:
        bot.reply_to(message, "❌ Invalid numbers or format")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['close'])
def manual_close(message):
    """Manually close a position"""
    global last_activity_time
    last_activity_time = datetime.now()
    
    try:
        parts = message.text.split()
        
        # /close TICKER PRICE
        # /close ALERT_ID PRICE
        
        if len(parts) < 3:
            bot.reply_to(message,
                "⚠️ **Usage:**\n\n"
                "`/close TICKER PRICE`\n"
                "Example: `/close NVDA 982`\n\n"
                "`/close ALERT_ID PRICE`\n"
                "Example: `/close abc123 982`",
                parse_mode="Markdown")
            return
        
        identifier = parts[1].upper()
        exit_price = float(parts[2])
        
        # Try to find in My_Trades first
        pnl, error = position_tracker.close_position_manual(identifier, exit_price, sheet_type='my')
        
        if error:
            # Try alert ID
            bot.reply_to(message, f"❌ {error}")
            return
        
        color = "🟢" if pnl['dollar'] > 0 else "🔴"
        status = "PROFIT" if pnl['dollar'] > 0 else "LOSS"
        
        msg = (
            f"✅ **Position Closed Manually** {color}\n\n"
            f"**{identifier}**\n"
            f"Exit: ${exit_price:.2f}\n\n"
            f"💰 P&L: ${pnl['dollar']:+,.2f} ({pnl['percent']:+.1f}%)\n"
            f"Status: {status}\n\n"
            f"📊 Updated in My_Trades sheet"
        )
        
        bot.reply_to(message, msg, parse_mode="Markdown")
    
    except ValueError:
        bot.reply_to(message, "❌ Invalid price")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['performance'])
def show_performance(message):
    """Show detailed performance comparison"""
    try:
        bot_perf = position_tracker.sheets.bot_performance.get_all_records()
        my_perf = position_tracker.sheets.my_performance.get_all_records()
        
        if not bot_perf and not my_perf:
            bot.reply_to(message, "📊 No performance data yet")
            return
        
        # Latest data
        bot_latest = bot_perf[-1] if bot_perf else {}
        my_latest = my_perf[-1] if my_perf else {}
        
        msg = (
            f"📊 **PERFORMANCE COMPARISON**\n\n"
            f"🤖 **Bot Performance (All Alerts):**\n"
            f"  Win Rate: {bot_latest.get('Win_Rate%', 'N/A')}\n"
            f"  Net P&L: {bot_latest.get('Net_PnL', 'N/A')}\n"
            f"  Total Trades: {bot_latest.get('Total_Trades', 0)}\n\n"
            f"👤 **Your Performance (Actual Trades):**\n"
            f"  Win Rate: {my_latest.get('Win_Rate%', 'N/A')}\n"
            f"  Net P&L: {my_latest.get('Net_PnL', 'N/A')}\n"
            f"  Total Trades: {my_latest.get('Total_Trades', 0)}\n\n"
            f"📈 Check Google Sheets for full details!"
        )
        
        bot.reply_to(message, msg, parse_mode="Markdown")
    
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

#==========================================
# AUTO SCANNER
# ==========================================
def scanner_loop():
    print("="*70)
    print("🚀 ULTIMATE TRADING BOT v2.0 (Smart Alerts + Daily Reset + Position Tracking)")
    print("="*70)
    print("📊 Execution: SHARES (proven 89% return)")
    print("⚡ Insights: OPTIONS (manual consideration)")
    print("🎯 Thresholds: Bull ≥65, Bear ≤40, ADX >20")
    print("⏰ Active: 6:00 AM - 5:00 PM EST")
    print("📈 Scanning: S&P 300 + Yahoo Top 30")
    print("🔔 Smart Alerts: Only on direction changes or significant score moves")
    print("⏱️  Timing: 6-9 AM (60min) | 9 AM-4 PM (30min) | 4-5 PM (45min)")
    print("🌅 Daily Reset: Memory clears at midnight EST (fresh start)")
    print("📝 Position Tracking: Google Sheets with stop/target alerts")
    print("="*70 + "\n")
    
    analysis_cache = {}
    cache_expiry = 900
    
    last_alerts = {}
    
    tz = pytz.timezone('US/Eastern')
    current_day = datetime.now(tz).date()
    
    print(f"📅 Trading day: {current_day.strftime('%Y-%m-%d')}")
    print(f"🔄 Alert memory initialized\n")
    
    while True:
        try:
            tz = pytz.timezone('US/Eastern')
            now = datetime.now(tz)
            today = now.date()
            
            # MIDNIGHT RESET
            if today != current_day:
                print("\n" + "="*70)
                print(f"🌅 NEW TRADING DAY: {today.strftime('%Y-%m-%d')}")
                print("="*70)
                print(f"🔄 Resetting alert memory (yesterday: {len(last_alerts)} stocks tracked)")
                print(f"📊 Fresh analysis starts now")
                print("="*70 + "\n")
                
                last_alerts = {}
                current_day = today
            
            # Determine scan interval
            if 6 <= now.hour < 9:
                scan_interval = 3600
                interval_name = "60 min"
            elif 9 <= now.hour < 16:
                scan_interval = 1800
                interval_name = "30 min"
            elif 16 <= now.hour < 17:
                scan_interval = 2700
                interval_name = "45 min"
            else:
                scan_interval = None
            
            # 6 AM - 5 PM EST
            if 6 <= now.hour < 17 and now.weekday() < 5:
                tickers = get_scan_tickers()
                print(f"🔍 Scan at {now.strftime('%H:%M')} EST | {len(tickers)} tickers | Next: {interval_name}")
                print(f"📊 Tracking {len(last_alerts)} stocks for duplicates\n")
                
                alerts_sent = 0
                duplicates_skipped = 0
                errors = 0
                
                for idx, ticker in enumerate(tickers, 1):
                    try:
                        time.sleep(0.5)
                        
                        cache_key = f"{ticker}_{now.strftime('%Y%m%d%H%M')[:11]}"
                        if cache_key in analysis_cache:
                            cached_time, cached_data = analysis_cache[cache_key]
                            if time.time() - cached_time < cache_expiry:
                                data = cached_data
                            else:
                                data = analyze_stock(ticker, strict=True)
                                analysis_cache[cache_key] = (time.time(), data)
                        else:
                            data = analyze_stock(ticker, strict=True)
                            analysis_cache[cache_key] = (time.time(), data)
                        
                        if data:
                            # DUPLICATE ALERT PREVENTION
                            should_alert = False
                            alert_reason = ""
                            
                            if ticker not in last_alerts:
                                should_alert = True
                                alert_reason = "NEW"
                            else:
                                last = last_alerts[ticker]
                                
                                if last['direction'] != data['direction']:
                                    should_alert = True
                                    alert_reason = f"🔄 {last['direction']}→{data['direction']}"
                                
                                elif abs(last['score'] - data['score']) >= 10:
                                    should_alert = True
                                    alert_reason = f"📊 Score {last['score']}→{data['score']}"
                                
                                elif time.time() - last['time'] > 14400:
                                    should_alert = True
                                    alert_reason = "⏰ Stale (>4hrs)"
                                
                                else:
                                    should_alert = False
                                    duplicates_skipped += 1
                            
                            if should_alert:
                                try:
                                    bot.send_message(YOUR_CHAT_ID, generate_alert_message(data), parse_mode="Markdown")
                                    
                                    # NEW: Track position in Google Sheets
                                    position_id = position_tracker.track_entry({
                                        'ticker': data['ticker'],
                                        'direction': data['direction'],
                                        'price': data['price'],
                                        'stop': data['shares_trade']['stop'],
                                        'target': data['shares_trade']['target'],
                                        'shares': data['shares_trade']['shares'],
                                        'score': data['score'],
                                        'reasons': data['reasons']
                                    }, trade_type='SHARES')
                                    
                                    if position_id:
                                        print(f"  📝 Position tracked: {position_id}")
                                    
                                    last_alerts[ticker] = {
                                        'direction': data['direction'],
                                        'score': data['score'],
                                        'time': time.time()
                                    }
                                    
                                    log_entry = {
                                        "Time": now.strftime("%Y-%m-%d %H:%M"),
                                        "Ticker": ticker,
                                        "Direction": data['direction'],
                                        "Price": data['price'],
                                        "Score": data['score'],
                                        "Reasons": "; ".join(data['reasons'][:3]),
                                        "Alert_Reason": alert_reason
                                    }
                                    log_trade_to_csv(log_entry)
                                    
                                    alerts_sent += 1
                                    print(f"  [{idx}/{len(tickers)}] ✅ {ticker} {data['direction']} ({data['score']}) - {alert_reason}")
                                    time.sleep(2)
                                
                                except Exception as e:
                                    print(f"  [{idx}/{len(tickers)}] ❌ Telegram error: {e}")
                                    errors += 1
                        
                        if idx % 50 == 0:
                            print(f"\n  📊 Progress: {idx}/{len(tickers)} ({idx/len(tickers)*100:.1f}%)")
                            print(f"  ✅ Sent: {alerts_sent} | ⏭️  Skipped: {duplicates_skipped} | ❌ Errors: {errors}\n")
                    
                    except Exception as e:
                        errors += 1
                        if "429" in str(e):
                            print(f"  ⚠️ Rate limited! Sleeping 60s...")
                            time.sleep(60)
                        continue
                
                # NEW: Check for position exits
                check_position_exits()
                
                # Clean cache
                current_time = time.time()
                analysis_cache = {k: v for k, v in analysis_cache.items() 
                                if current_time - v[0] < cache_expiry}
                
                print(f"\n💤 Scan complete at {now.strftime('%H:%M')}")
                print(f"   ✅ New alerts sent: {alerts_sent}")
                print(f"   ⏭️  Duplicates skipped: {duplicates_skipped}")
                print(f"   ❌ Errors: {errors}")
                print(f"   ⏱️  Next scan in {interval_name}\n")
                time.sleep(scan_interval)
            
            else:
                next_scan = "6:00 AM" if now.hour < 6 else "tomorrow 6:00 AM"
                time.sleep(600)
        
        except Exception as e:
            print(f"❌ Scanner error: {e}")
            time.sleep(60)

# ==========================================
# FLASK SERVER
# ==========================================
@app.route('/')
def index():
    return "🤖 Ultimate Trading Bot v2.0 (Position Tracking Enabled)", 200

@app.route('/health')
def health():
    return {"status": "healthy", "version": "2.0", "features": ["signals", "position_tracking"]}

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("\n🚀 Starting Ultimate Trading Bot v2.0...\n")
    
    t_scan = threading.Thread(target=scanner_loop, daemon=True)
    t_scan.start()
    
    t_bot = threading.Thread(target=bot.infinity_polling, daemon=True)
    t_bot.start()
    
    run_server()