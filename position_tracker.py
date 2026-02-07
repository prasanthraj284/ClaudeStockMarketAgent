"""
Position Tracker - Dual System
Handles both bot alerts and your manual trades
"""
from sheets_handler import PositionSheet
from datetime import datetime
import uuid

class PositionTracker:
    def __init__(self):
        """Initialize with Google Sheets"""
        self.sheets = PositionSheet()
        print("✅ Position Tracker ready\n")
        
        # Store alert metadata for easy reference
        self.alert_metadata = {}  # {alert_id: {ticker, direction, price, stop, target, etc}}
    
    def track_bot_alert(self, signal_data):
        """
        Track bot alert in Bot_Alerts sheet
        
        Args:
            signal_data: {alert_id, ticker, direction, price, stop, target, shares, score, reasons}
        """
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
        """
        User entered a trade from bot alert
        Tracks in My_Trades sheet with user's actual entry
        
        Args:
            alert_id: The alert ID from bot
            entry_price: User's actual entry price
            quantity: Shares or contracts
            trade_type: 'SHARES', 'CALL', 'PUT'
            premium: For options
        """
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
            stop = entry_price * 0.7  # -30%
            target = entry_price * 1.5  # +50%
        
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
        User found their own trade (not from bot alert)
        Tracks ONLY in My_Trades sheet
        """
        position_id = str(uuid.uuid4())[:8]
        
        position = {
            'id': position_id,
            'entry_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'ticker': ticker,
            'direction': direction,
            'type': trade_type,
            'entry_price': entry_price,
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
        Check if any open positions hit stop/target
        Checks BOTH Bot_Alerts and My_Trades sheets
        """
        exits = []
        open_positions = self.sheets.get_open_positions(sheet_type='both')
        
        if not open_positions:
            return exits
        
        print(f"\n🔍 Checking {len(open_positions)} open positions...")
        
        for pos in open_positions:
            ticker = pos['Ticker']
            if ticker not in current_prices:
                continue
            
            price = current_prices[ticker]
            entry = float(pos['Entry_Price'])
            stop = float(pos['Stop'])
            target = float(pos['Target'])
            
            if pos['Direction'] == 'BULL':
                if price['low'] <= stop:
                    exits.append({
                        'position': pos,
                        'exit_price': stop,
                        'exit_reason': 'STOP',
                        'status': 'CLOSED_LOSS'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🛑 {ticker} STOP hit: ${stop:.2f} ({sheet_name})")
                
                elif price['high'] >= target:
                    exits.append({
                        'position': pos,
                        'exit_price': target,
                        'exit_reason': 'TARGET',
                        'status': 'CLOSED_PROFIT'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🎯 {ticker} TARGET hit: ${target:.2f} ({sheet_name})")
            
            elif pos['Direction'] == 'BEAR':
                if price['high'] >= stop:
                    exits.append({
                        'position': pos,
                        'exit_price': stop,
                        'exit_reason': 'STOP',
                        'status': 'CLOSED_LOSS'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🛑 {ticker} STOP hit: ${stop:.2f} ({sheet_name})")
                
                elif price['low'] <= target:
                    exits.append({
                        'position': pos,
                        'exit_price': target,
                        'exit_reason': 'TARGET',
                        'status': 'CLOSED_PROFIT'
                    })
                    sheet_type = pos.get('sheet_type', 'bot')
                    sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
                    print(f"  🎯 {ticker} TARGET hit: ${target:.2f} ({sheet_name})")
        
        if not exits:
            print("  ✓ All positions in range")
        
        return exits
    
    def process_exits(self, exits):
        """Process exits and return alert data"""
        alerts = []
        
        for exit in exits:
            pos = exit['position']
            sheet_type = pos.get('sheet_type', 'bot')
            
            # Calculate P&L
            pnl = self.calculate_pnl(
                pos['Direction'],
                pos['Type'],
                float(pos['Entry_Price']),
                float(exit['exit_price']),
                float(pos['Quantity'])
            )
            
            # Update sheet
            exit_data = {
                'status': exit['status'],
                'exit_price': exit['exit_price'],
                'exit_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'exit_reason': exit['exit_reason'],
                'pnl_dollar': pnl['dollar'],
                'pnl_percent': pnl['percent']
            }
            
            self.sheets.update_exit(pos['ID'], exit_data, sheet_type=sheet_type)
            
            # Alert data
            alerts.append({
                'ticker': pos['Ticker'],
                'direction': pos['Direction'],
                'type': pos['Type'],
                'entry': float(pos['Entry_Price']),
                'exit': float(exit['exit_price']),
                'quantity': float(pos['Quantity']),
                'reason': exit['exit_reason'],
                'pnl': pnl,
                'sheet_type': sheet_type
            })
        
        if exits:
            # Update both performance sheets
            self.sheets.update_performance(sheet_type='bot')
            self.sheets.update_performance(sheet_type='my')
        
        return alerts
    
    def calculate_pnl(self, direction, trade_type, entry, exit, quantity):
        """Calculate P&L"""
        if trade_type == 'SHARES':
            if direction == 'BULL':
                pnl_per = exit - entry
            else:
                pnl_per = entry - exit
            
            pnl_dollar = pnl_per * quantity - 2
            pnl_percent = (pnl_per / entry) * 100
        
        else:  # OPTIONS
            if direction == 'BULL':
                pnl_per = (exit - entry) * 100
            else:
                pnl_per = (entry - exit) * 100
            
            pnl_dollar = pnl_per * quantity - 2
            pnl_percent = ((exit - entry) / entry) * 100
        
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
            float(pos['Quantity'])
        )
        
        status = 'CLOSED_PROFIT' if pnl['dollar'] > 0 else 'CLOSED_LOSS'
        
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
            self.sheets.update_performance(sheet_type=sheet_type)
            return pnl, None
        else:
            return None, "Failed to update sheet"