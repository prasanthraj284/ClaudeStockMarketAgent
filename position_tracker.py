"""
Position Tracker - FIXED VERSION
- Proper exit tracking (no duplicate alerts)
- Stock-price based options tracking (±5%)
- Expiry date monitoring
"""
from sheets_handler import PositionSheet
from datetime import datetime, timedelta
import uuid
import yfinance as yf

class PositionTracker:
    def __init__(self):
        """Initialize with Google Sheets"""
        self.sheets = PositionSheet()
        print("✅ Position Tracker ready (FIXED VERSION)\n")
        
        # Store alert metadata for easy reference
        self.alert_metadata = {}
        
        # Track which positions we've already alerted exits for
        self.alerted_exits = set()  # Set of position IDs we've already sent exit alerts for
    
    def track_bot_alert(self, signal_data):
        """Track bot alert in Bot_Alerts sheet"""
        position = {
            'id': signal_data['alert_id'],
            'entry_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'ticker': signal_data['ticker'],
            'direction': signal_data['direction'],
            'type': 'SHARES',
            'entry_price': signal_data['price'],
            'stop': signal_data['stop'],
            'target': signal_data['target'],
            'quantity': signal_data.get('shares', 0),
            'score': signal_data['score'],
            'reasons': '; '.join(signal_data['reasons'][:3])
        }
        
        # Store metadata
        self.alert_metadata[signal_data['alert_id']] = {
            'ticker': signal_data['ticker'],
            'direction': signal_data['direction'],
            'price': signal_data['price'],
            'stop': signal_data['stop'],
            'target': signal_data['target'],
            'shares': signal_data.get('shares', 0)
        }
        
        self.sheets.add_position(position, sheet_type='bot')
        return signal_data['alert_id']
    
    def track_user_entry_from_alert(self, alert_id, entry_price, quantity, trade_type='SHARES', premium=None):
        """User entered a trade from bot alert"""
        if alert_id not in self.alert_metadata:
            return None, "Alert ID not found"
        
        metadata = self.alert_metadata[alert_id]
        
        # Calculate stop/target based on user's entry
        if trade_type == 'SHARES':
            atr_estimate = abs(metadata['target'] - metadata['price']) / 3.5
            
            if metadata['direction'] == 'BULL':
                stop = entry_price - (atr_estimate * 2.5)
                target = entry_price + (atr_estimate * 3.5)
            else:
                stop = entry_price + (atr_estimate * 2.0)
                target = entry_price - (atr_estimate * 4.0)
        else:
            # Options - use simple percentages
            stop = entry_price * 0.7
            target = entry_price * 1.5
        
        position_id = str(uuid.uuid4())[:8]
        
        position = {
            'id': position_id,
            'entry_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'ticker': metadata['ticker'],
            'direction': metadata['direction'],
            'type': trade_type,
            'entry_price': entry_price,
            'stop': stop,
            'target': target,
            'quantity': quantity,
            'premium': premium if trade_type in ['CALL', 'PUT'] else '',
            'reasons': f"From alert {alert_id}"
        }
        
        self.sheets.add_position(position, sheet_type='my')
        return position_id, None
    
    def track_manual_trade(self, ticker, direction, trade_type, entry_price, stop, target, quantity, 
                          strike=None, expiry=None, premium=None):
        """
        User found their own trade
        
        For OPTIONS: entry_price = current stock price
                    premium = option premium paid
                    stop/target = stock price levels (±5% from entry_price)
        """
        position_id = str(uuid.uuid4())[:8]
        
        # For options, get current stock price if not provided
        if trade_type in ['CALL', 'PUT']:
            try:
                stock = yf.Ticker(ticker)
                current_stock_price = float(stock.history(period='1d')['Close'].iloc[-1])
                
                # Auto-calculate stop/target based on ±5% from current stock price
                if trade_type == 'PUT':
                    # PUT: Profit when stock goes DOWN, loss when goes UP
                    stop = current_stock_price * 1.05  # +5% stock price (bad for put)
                    target = current_stock_price * 0.95  # -5% stock price (good for put)
                else:  # CALL
                    # CALL: Profit when stock goes UP, loss when goes DOWN
                    stop = current_stock_price * 0.95  # -5% stock price (bad for call)
                    target = current_stock_price * 1.05  # +5% stock price (good for call)
                
                # Store current stock price as "entry_price" for tracking
                entry_price = current_stock_price
                
            except Exception as e:
                print(f"⚠️ Couldn't get stock price for {ticker}: {e}")
                # Fallback to provided values
        
        position = {
            'id': position_id,
            'entry_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'ticker': ticker,
            'direction': direction,
            'type': trade_type,
            'entry_price': entry_price,  # For options: stock price at entry
            'stop': stop,
            'target': target,
            'quantity': quantity,
            'strike': strike or '',
            'expiry': expiry or '',
            'premium': premium or '',
            'reasons': 'Manual trade (not from bot)'
        }
        
        self.sheets.add_position(position, sheet_type='my')
        return position_id
    
    def check_exits(self, current_prices):
        """
        FIXED: Check exits and prevent duplicates
        """
        exits = []
        
        # Get ONLY open positions (Status = "OPEN")
        open_positions = self.sheets.get_open_positions(sheet_type='both')
        
        # Filter out positions we've already alerted
        open_positions = [p for p in open_positions if p['ID'] not in self.alerted_exits]
        
        if not open_positions:
            return exits
        
        print(f"\n🔍 Checking {len(open_positions)} open positions...")
        
        for pos in open_positions:
            ticker = pos['Ticker']
            position_type = pos['Type']
            
            if ticker not in current_prices:
                continue
            
            price_data = current_prices[ticker]
            current_price = price_data['current']
            entry = float(pos['Entry_Price'])
            stop = float(pos['Stop'])
            target = float(pos['Target'])
            
            # Check expiry FIRST (for options)
            if position_type in ['CALL', 'PUT'] and pos.get('Expiry'):
                try:
                    expiry_date = datetime.strptime(pos['Expiry'], '%Y-%m-%d')
                    today = datetime.now()
                    
                    # If expired or expiring today
                    if today.date() >= expiry_date.date():
                        exits.append({
                            'position': pos,
                            'exit_price': current_price,
                            'exit_reason': 'EXPIRED',
                            'status': 'CLOSED_EXPIRED'
                        })
                        sheet_type = pos.get('sheet_type', 'bot')
                        sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                        print(f"  ⏰ {ticker} EXPIRED ({sheet_name})")
                        continue  # Don't check stop/target if expired
                except:
                    pass
            
            # For SHARES and OPTIONS, check stop/target using stock price
            if pos['Direction'] == 'BULL':
                # BULL: Long shares or CALL option
                if price_data['low'] <= stop:
                    exits.append({
                        'position': pos,
                        'exit_price': stop,
                        'exit_reason': 'STOP',
                        'status': 'CLOSED_LOSS'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🛑 {ticker} STOP hit: {stop:.2f} ({sheet_name})")
                
                elif price_data['high'] >= target:
                    exits.append({
                        'position': pos,
                        'exit_price': target,
                        'exit_reason': 'TARGET',
                        'status': 'CLOSED_PROFIT'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🎯 {ticker} TARGET hit: {target:.2f} ({sheet_name})")
            
            elif pos['Direction'] == 'BEAR':
                # BEAR: Short shares or PUT option
                if price_data['high'] >= stop:
                    exits.append({
                        'position': pos,
                        'exit_price': stop,
                        'exit_reason': 'STOP',
                        'status': 'CLOSED_LOSS'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🛑 {ticker} STOP hit: {stop:.2f} ({sheet_name})")
                
                elif price_data['low'] <= target:
                    exits.append({
                        'position': pos,
                        'exit_price': target,
                        'exit_reason': 'TARGET',
                        'status': 'CLOSED_PROFIT'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🎯 {ticker} TARGET hit: {target:.2f} ({sheet_name})")
        
        if not exits:
            print("  ✓ All positions in range")
        
        return exits
    
    def process_exits(self, exits):
        """
        FIXED: Process exits and mark as alerted to prevent duplicates
        """
        alerts = []
        
        for exit in exits:
            pos = exit['position']
            sheet_type = pos.get('sheet_type', 'bot')
            position_id = pos['ID']
            
            # Calculate P&L
            pnl = self.calculate_pnl(
                pos['Direction'],
                pos['Type'],
                float(pos['Entry_Price']),
                float(exit['exit_price']),
                float(pos['Quantity']),
                pos.get('Premium', '')
            )
            
            # Update sheet with CLOSED status
            exit_data = {
                'status': exit['status'],
                'exit_price': exit['exit_price'],
                'exit_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'exit_reason': exit['exit_reason'],
                'pnl_dollar': pnl['dollar'],
                'pnl_percent': pnl['percent']
            }
            
            success = self.sheets.update_exit(position_id, exit_data, sheet_type=sheet_type)
            
            if success:
                # Mark this position as alerted (PREVENT DUPLICATES)
                self.alerted_exits.add(position_id)
            
            # Prepare alert data
            alerts.append({
                'ticker': pos['Ticker'],
                'direction': pos['Direction'],
                'type': pos['Type'],
                'entry': float(pos['Entry_Price']),
                'exit': float(exit['exit_price']),
                'quantity': float(pos['Quantity']),
                'reason': exit['exit_reason'],
                'pnl': pnl,
                'sheet_type': sheet_type,
                'strike': pos.get('Strike', ''),
                'expiry': pos.get('Expiry', ''),
                'premium': pos.get('Premium', '')
            })
        
        if exits:
            # Update performance sheets
            self.sheets.update_performance(sheet_type='bot')
            self.sheets.update_performance(sheet_type='my')
        
        return alerts
    
    def check_expirations(self):
        """Check for upcoming option expirations (3 days, 1 day warnings)"""
        warnings = []
        
        open_positions = self.sheets.get_open_positions(sheet_type='both')
        
        for pos in open_positions:
            if pos['Type'] not in ['CALL', 'PUT']:
                continue
            
            if not pos.get('Expiry'):
                continue
            
            try:
                expiry_date = datetime.strptime(pos['Expiry'], '%Y-%m-%d')
                today = datetime.now()
                days_to_expiry = (expiry_date - today).days
                
                # Warning at 3 days and 1 day before expiry
                if days_to_expiry in [3, 1]:
                    warnings.append({
                        'position': pos,
                        'days': days_to_expiry
                    })
            except:
                continue
        
        return warnings
    
    def calculate_pnl(self, direction, trade_type, entry, exit, quantity, premium=''):
        """
        Calculate P&L
        
        For OPTIONS: entry/exit are STOCK PRICES, premium is option cost
                    P&L is approximate (we don't know actual premium at exit)
        """
        if trade_type == 'SHARES':
            if direction == 'BULL':
                pnl_per = exit - entry
            else:
                pnl_per = entry - exit
            
            pnl_dollar = pnl_per * quantity - 2
            pnl_percent = (pnl_per / entry) * 100
        
        else:  # OPTIONS
            # For options, we tracked stock price movement
            # We can't calculate exact P&L without knowing exit premium
            # Return stock movement % as indicator
            if direction == 'BULL':  # CALL
                stock_move_pct = ((exit - entry) / entry) * 100
            else:  # PUT
                stock_move_pct = ((entry - exit) / entry) * 100
            
            pnl_dollar = 0  # Unknown without actual exit premium
            pnl_percent = stock_move_pct
        
        return {
            'dollar': round(pnl_dollar, 2),
            'percent': round(pnl_percent, 2)
        }
    
    def close_position_manual(self, ticker, exit_price, sheet_type='my'):
        """Manually close a position"""
        pos = self.sheets.find_position_by_ticker(ticker, sheet_type=sheet_type)
        
        if not pos:
            return None, f"No open {sheet_type} position found for {ticker}"
        
        pnl = self.calculate_pnl(
            pos['Direction'],
            pos['Type'],
            float(pos['Entry_Price']),
            float(exit_price),
            float(pos['Quantity']),
            pos.get('Premium', '')
        )
        
        status = 'CLOSED_PROFIT' if pnl['percent'] > 0 else 'CLOSED_LOSS'
        
        exit_data = {
            'status': status,
            'exit_price': exit_price,
            'exit_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'exit_reason': 'MANUAL',
            'pnl_dollar': pnl['dollar'],
            'pnl_percent': pnl['percent']
        }
        
        success = self.sheets.update_exit(pos['ID'], exit_data, sheet_type=sheet_type)
        
        if success:
            # Mark as alerted to prevent duplicates
            self.alerted_exits.add(pos['ID'])
            self.sheets.update_performance(sheet_type=sheet_type)
            return pnl, None
        else:
            return None, "Failed to update sheet"
