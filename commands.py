"""
Trading Bot Commands Module
All Telegram bot command handlers in one place
"""

from datetime import datetime

def register_commands(bot, position_tracker, YOUR_CHAT_ID):
    """
    Register all bot commands
    
    Args:
        bot: Telebot instance
        position_tracker: PositionTracker instance
        YOUR_CHAT_ID: Your Telegram chat ID
    """
    
    # Track activity for health checks
    last_activity_time = datetime.now()
    
    def update_activity():
        nonlocal last_activity_time
        last_activity_time = datetime.now()
        return last_activity_time
    
    @bot.message_handler(commands=['help'])
    def show_help(message):
        """Complete help guide"""
        help_text = """
🤖 **TRADING BOT COMMANDS**

━━━━━━━━━━━━━━━━━━━━━━━━
📊 **CHECKING SIGNALS**
━━━━━━━━━━━━━━━━━━━━━━━━

/check TICKER
Example: `/check NVDA`
→ Get analysis (does NOT track)

/scan
→ Force scan top 20 movers

━━━━━━━━━━━━━━━━━━━━━━━━
📝 **ENTERING TRADES**
━━━━━━━━━━━━━━━━━━━━━━━━

**From Bot Alert (with ID):**

/entered ALERT_ID shares PRICE
Example: `/entered abc123 shares 915`
→ Tracks in BOTH sheets

/entered ALERT_ID options CONTRACTS PREMIUM
Example: `/entered abc123 options 2 36.50`
→ For options from bot alert

**Manual Trade (you found it):**

/buy TICKER shares PRICE stop STOP target TARGET
Example: `/buy AAPL shares 185 stop 180 target 195`
→ Tracks in YOUR sheet only

━━━━━━━━━━━━━━━━━━━━━━━━
🚪 **CLOSING POSITIONS**
━━━━━━━━━━━━━━━━━━━━━━━━

/close TICKER PRICE
Example: `/close NVDA 982`
→ Manually close position

━━━━━━━━━━━━━━━━━━━━━━━━
📊 **VIEWING INFO**
━━━━━━━━━━━━━━━━━━━━━━━━

/positions - See all open positions
/stats - Trading statistics
/performance - Bot vs You comparison

━━━━━━━━━━━━━━━━━━━━━━━━
💡 **EXAMPLES**
━━━━━━━━━━━━━━━━━━━━━━━━

**Scenario 1: Bot alerts, you enter**
Bot: 🚀 NVDA BULL @ $905 (ID: abc123)
You: `/entered abc123 shares 915`
✅ Tracked in both sheets

**Scenario 2: You find your own trade**
You: `/buy TSLA shares 245 stop 230 target 275`
✅ Tracked in YOUR sheet only

**Scenario 3: Manual close**
You: `/close NVDA 982`
✅ Closes position, shows P&L

━━━━━━━━━━━━━━━━━━━━━━━━
🔔 **ALERTS**
━━━━━━━━━━━━━━━━━━━━━━━━

Bot sends:
✅ Entry signals (when found)
✅ Exit alerts (stop/target hit)
✅ Health checks (hourly if quiet)

Need help? Type /help anytime!
"""
        bot.reply_to(message, help_text, parse_mode="Markdown")
    
    @bot.message_handler(commands=['commands'])
    def show_quick_commands(message):
        """Quick command reference"""
        cmd_text = """
📝 **QUICK COMMANDS**

/check TICKER - Check stock
/entered ID shares PRICE - Enter from alert
/buy TICKER shares PRICE stop X target Y - Manual trade
/close TICKER PRICE - Close position
/positions - View open positions
/stats - See stats
/performance - Compare bot vs you
/help - Full guide with examples
"""
        bot.reply_to(message, cmd_text, parse_mode="Markdown")
    
    @bot.message_handler(commands=['entered'])
    def entered_from_alert(message):
        """User entered a trade from bot alert"""
        update_activity()
        
        try:
            parts = message.text.split()
            
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
                
                if alert_id not in position_tracker.alert_metadata:
                    bot.reply_to(message, f"❌ Alert ID '{alert_id}' not found.\n\nTip: IDs are lost on restart. Try:\n`/buy {alert_id} shares {entry_price} stop X target Y`")
                    return
                
                metadata = position_tracker.alert_metadata[alert_id]
                quantity = metadata.get('shares', 27)
                
                position_id, error = position_tracker.track_user_entry_from_alert(
                    alert_id, entry_price, quantity, 'SHARES'
                )
                
                if error:
                    bot.reply_to(message, f"❌ {error}")
                    return
                
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
                    f"  ✅ Bot_Alerts (bot price: ${metadata['price']:.2f})\n"
                    f"  ✅ My_Trades (your price: ${entry_price:.2f})\n\n"
                    f"🔔 I'll alert you on exit!"
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
                    f"**{metadata['ticker']}** OPTIONS\n"
                    f"Contracts: {contracts}\n"
                    f"Premium: ${premium:.2f}\n"
                    f"Stop: ${stop:.2f} (-30%)\n"
                    f"Target: ${target:.2f} (+50%)\n\n"
                    f"📊 Tracked in My_Trades\n\n"
                    f"🔔 I'll alert you on exit!"
                )
                
                bot.reply_to(message, msg, parse_mode="Markdown")
        
        except ValueError:
            bot.reply_to(message, "❌ Invalid numbers. Check your format.")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")
    
    @bot.message_handler(commands=['buy'])
    def manual_buy(message):
        """User found their own trade"""
        update_activity()
        
        try:
            parts = message.text.split()
            
            if len(parts) < 5:
                bot.reply_to(message,
                    "⚠️ **Usage:**\n\n"
                    "Shares: `/buy TICKER shares PRICE stop STOP target TARGET`\n"
                    "Example: `/buy AAPL shares 185 stop 180 target 195`",
                    parse_mode="Markdown")
                return
            
            ticker = parts[1].upper()
            trade_type_input = parts[2].lower()
            
            if trade_type_input == 'shares':
                entry_price = float(parts[3])
                
                stop_idx = parts.index('stop') if 'stop' in parts else None
                target_idx = parts.index('target') if 'target' in parts else None
                
                if not stop_idx or not target_idx:
                    bot.reply_to(message, "❌ Missing 'stop' or 'target' keyword")
                    return
                
                stop = float(parts[stop_idx + 1])
                target = float(parts[target_idx + 1])
                
                if target > entry_price:
                    direction = 'BULL'
                else:
                    direction = 'BEAR'
                
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
                    f"(You found this, not bot!)\n\n"
                    f"🔔 I'll alert you on exit!"
                )
                
                bot.reply_to(message, msg, parse_mode="Markdown")
        
        except ValueError:
            bot.reply_to(message, "❌ Invalid numbers")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")
    
    @bot.message_handler(commands=['close'])
    def manual_close(message):
        """Manually close a position"""
        update_activity()
        
        try:
            parts = message.text.split()
            
            if len(parts) < 3:
                bot.reply_to(message,
                    "⚠️ **Usage:**\n\n"
                    "`/close TICKER PRICE`\n"
                    "Example: `/close NVDA 982`",
                    parse_mode="Markdown")
                return
            
            ticker = parts[1].upper()
            exit_price = float(parts[2])
            
            pnl, error = position_tracker.close_position_manual(ticker, exit_price, sheet_type='my')
            
            if error:
                bot.reply_to(message, f"❌ {error}")
                return
            
            color = "🟢" if pnl['dollar'] > 0 else "🔴"
            status = "PROFIT" if pnl['dollar'] > 0 else "LOSS"
            
            msg = (
                f"✅ **Position Closed** {color}\n\n"
                f"**{ticker}**\n"
                f"Exit: ${exit_price:.2f}\n\n"
                f"💰 P&L: ${pnl['dollar']:+,.2f} ({pnl['percent']:+.1f}%)\n"
                f"Status: {status}\n\n"
                f"📊 Updated in My_Trades"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        
        except ValueError:
            bot.reply_to(message, "❌ Invalid price")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")
    
    @bot.message_handler(commands=['performance'])
    def show_performance(message):
        """Show performance comparison"""
        try:
            bot_perf = position_tracker.sheets.bot_performance.get_all_records()
            my_perf = position_tracker.sheets.my_performance.get_all_records()
            
            if not bot_perf and not my_perf:
                bot.reply_to(message, "📊 No performance data yet")
                return
            
            bot_latest = bot_perf[-1] if bot_perf else {}
            my_latest = my_perf[-1] if my_perf else {}
            
            msg = (
                f"📊 **PERFORMANCE COMPARISON**\n\n"
                f"🤖 **Bot (All Alerts):**\n"
                f"  Win Rate: {bot_latest.get('Win_Rate%', 'N/A')}\n"
                f"  Net P&L: {bot_latest.get('Net_PnL', 'N/A')}\n"
                f"  Trades: {bot_latest.get('Total_Trades', 0)}\n\n"
                f"👤 **You (Actual Trades):**\n"
                f"  Win Rate: {my_latest.get('Win_Rate%', 'N/A')}\n"
                f"  Net P&L: {my_latest.get('Net_PnL', 'N/A')}\n"
                f"  Trades: {my_latest.get('Total_Trades', 0)}\n\n"
                f"📈 Check Google Sheets for details!"
            )
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        
        except Exception as e:
            bot.reply_to(message, f"Error: {e}")
    
    # Return the update_activity function so main bot can use it
    return update_activity