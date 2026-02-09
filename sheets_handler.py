"""
Google Sheets Handler - FIXED VERSION
- Proper exit status updates
- Better error handling
- No duplicate tracking
"""
import gspread
from google.oauth2.service_account import Credentials
from config import get_google_creds, SHEET_ID
from datetime import datetime
import time

class PositionSheet:
    def __init__(self):
        """Connect to Google Sheets"""
        print("\n🔗 Connecting to Google Sheets...")
        
        creds_dict = get_google_creds()
        
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        self.gc = gspread.authorize(creds)
        self.sheet = self.gc.open_by_key(SHEET_ID)
        
        print(f"✅ Connected to: {self.sheet.title}\n")
        self.setup_sheets()
    
    def setup_sheets(self):
        """Create all required sheets"""
        headers = [
            'ID', 'Entry_Date', 'Ticker', 'Direction', 'Type',
            'Entry_Price', 'Stop', 'Target', 'Quantity',
            'Strike', 'Expiry', 'Premium', 'Score', 'Status',
            'Exit_Price', 'Exit_Date', 'Exit_Reason',
            'PnL_Dollar', 'PnL_Percent', 'Days_Held', 'Reasons'
        ]
        
        # Bot Alerts sheet
        try:
            self.bot_alerts = self.sheet.worksheet('Bot_Alerts')
            print("✓ Found 'Bot_Alerts' sheet")
        except:
            print("Creating 'Bot_Alerts' sheet...")
            self.bot_alerts = self.sheet.add_worksheet(title='Bot_Alerts', rows=1000, cols=25)
            self.bot_alerts.append_row(headers)
            self.format_header(self.bot_alerts, 'A1:U1')
        
        # My Trades sheet
        try:
            self.my_trades = self.sheet.worksheet('My_Trades')
            print("✓ Found 'My_Trades' sheet")
        except:
            print("Creating 'My_Trades' sheet...")
            self.my_trades = self.sheet.add_worksheet(title='My_Trades', rows=1000, cols=25)
            self.my_trades.append_row(headers)
            self.format_header(self.my_trades, 'A1:U1')
        
        # Bot Performance sheet
        try:
            self.bot_performance = self.sheet.worksheet('Bot_Performance')
            print("✓ Found 'Bot_Performance' sheet")
        except:
            print("Creating 'Bot_Performance' sheet...")
            self.bot_performance = self.sheet.add_worksheet(title='Bot_Performance', rows=1000, cols=10)
            perf_headers = ['Date', 'Total_Trades', 'Wins', 'Losses', 'Win_Rate%',
                          'Gross_Profit', 'Gross_Loss', 'Net_PnL']
            self.bot_performance.append_row(perf_headers)
            self.format_header(self.bot_performance, 'A1:H1')
        
        # My Performance sheet
        try:
            self.my_performance = self.sheet.worksheet('My_Performance')
            print("✓ Found 'My_Performance' sheet")
        except:
            print("Creating 'My_Performance' sheet...")
            self.my_performance = self.sheet.add_worksheet(title='My_Performance', rows=1000, cols=10)
            perf_headers = ['Date', 'Total_Trades', 'Wins', 'Losses', 'Win_Rate%',
                          'Gross_Profit', 'Gross_Loss', 'Net_PnL']
            self.my_performance.append_row(perf_headers)
            self.format_header(self.my_performance, 'A1:H1')
        
        print("✅ All sheets ready!\n")
    
    def format_header(self, worksheet, range_str):
        """Format header row"""
        try:
            worksheet.format(range_str, {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.2, 'green': 0.2, 'blue': 0.2},
                'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
            })
        except Exception as e:
            print(f"  ⚠️ Couldn't format header: {e}")
    
    def add_position(self, pos, sheet_type='bot'):
        """Add position to specified sheet"""
        row = [
            pos['id'], 
            pos['entry_date'], 
            pos['ticker'], 
            pos['direction'], 
            pos['type'],
            pos['entry_price'], 
            pos['stop'], 
            pos['target'], 
            pos['quantity'],
            pos.get('strike', ''), 
            pos.get('expiry', ''), 
            pos.get('premium', ''),
            pos.get('score', ''), 
            'OPEN',  # Status
            '', '', '', '', '', '',  # Exit columns
            pos.get('reasons', '')
        ]
        
        try:
            if sheet_type == 'bot':
                self.bot_alerts.append_row(row)
                print(f"  📝 Bot tracked: {pos['ticker']} {pos['direction']} (ID: {pos['id']})")
            else:
                self.my_trades.append_row(row)
                print(f"  📝 Your trade tracked: {pos['ticker']} {pos['direction']} (ID: {pos['id']})")
            
            time.sleep(1)  # Rate limit protection
            return True
        except Exception as e:
            print(f"  ❌ Error adding position: {e}")
            return False
    
    def get_open_positions(self, sheet_type='both'):
        """Get open positions from specified sheet(s) - ONLY Status='OPEN'"""
        positions = []
        
        try:
            if sheet_type in ['bot', 'both']:
                bot_records = self.bot_alerts.get_all_records()
                # CRITICAL: Filter for OPEN status only
                bot_open = [r for r in bot_records if r.get('Status') == 'OPEN']
                for pos in bot_open:
                    pos['sheet_type'] = 'bot'
                positions.extend(bot_open)
            
            if sheet_type in ['my', 'both']:
                my_records = self.my_trades.get_all_records()
                # CRITICAL: Filter for OPEN status only
                my_open = [r for r in my_records if r.get('Status') == 'OPEN']
                for pos in my_open:
                    pos['sheet_type'] = 'my'
                positions.extend(my_open)
            
            return positions
        
        except Exception as e:
            print(f"  ❌ Error getting open positions: {e}")
            return []
    
    def update_exit(self, position_id, exit_data, sheet_type='bot'):
        """
        FIXED: Update position with exit info and mark as CLOSED
        This is CRITICAL - if this fails, duplicates happen!
        """
        try:
            worksheet = self.bot_alerts if sheet_type == 'bot' else self.my_trades
            
            # Find the position by ID
            cell = worksheet.find(position_id)
            if not cell:
                print(f"  ❌ Position {position_id} not found in sheet!")
                return False
            
            row_num = cell.row
            
            # Calculate days held
            entry_date = worksheet.cell(row_num, 2).value
            try:
                entry = datetime.strptime(entry_date, '%Y-%m-%d %H:%M')
                exit_dt = datetime.strptime(exit_data['exit_date'], '%Y-%m-%d %H:%M')
                days = (exit_dt - entry).days
            except:
                days = 0
            
            # CRITICAL: Update ALL exit columns individually to avoid batch errors
            # Columns: N=Status, O=Exit_Price, P=Exit_Date, Q=Exit_Reason, R=PnL_Dollar, S=PnL_Percent, T=Days_Held
            
            # Update each column individually (more reliable with gspread)
            worksheet.update_acell(f'N{row_num}', str(exit_data['status']))           # Status
            worksheet.update_acell(f'O{row_num}', float(exit_data['exit_price']))     # Exit_Price
            worksheet.update_acell(f'P{row_num}', str(exit_data['exit_date']))        # Exit_Date
            worksheet.update_acell(f'Q{row_num}', str(exit_data['exit_reason']))      # Exit_Reason
            worksheet.update_acell(f'R{row_num}', float(exit_data['pnl_dollar']))     # PnL_Dollar
            worksheet.update_acell(f'S{row_num}', float(exit_data['pnl_percent']))    # PnL_Percent
            worksheet.update_acell(f'T{row_num}', int(days))                          # Days_Held
            
            # Color code the row
            if exit_data['pnl_dollar'] > 0:
                bg = {'red': 0.85, 'green': 0.95, 'blue': 0.85}  # Green
            else:
                bg = {'red': 0.95, 'green': 0.85, 'blue': 0.85}  # Red
            
            try:
                worksheet.format(f'A{row_num}:U{row_num}', {'backgroundColor': bg})
            except:
                pass  # Color formatting is optional
            
            sheet_name = "Bot_Alerts" if sheet_type == 'bot' else "My_Trades"
            print(f"  ✅ Closed in {sheet_name}: {position_id} ({exit_data['status']})")
            
            time.sleep(1)  # Rate limit protection
            return True
            
        except Exception as e:
            print(f"  ❌ CRITICAL ERROR updating exit for {position_id}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def find_position_by_ticker(self, ticker, sheet_type='my'):
        """Find open position by ticker"""
        try:
            worksheet = self.bot_alerts if sheet_type == 'bot' else self.my_trades
            all_records = worksheet.get_all_records()
            
            # Find OPEN position with this ticker
            for record in all_records:
                if record['Ticker'] == ticker and record['Status'] == 'OPEN':
                    return record
            
            return None
        except Exception as e:
            print(f"  ❌ Error finding position: {e}")
            return None
    
    def update_performance(self, sheet_type='bot'):
        """Update daily performance stats"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            worksheet = self.bot_alerts if sheet_type == 'bot' else self.my_trades
            perf_sheet = self.bot_performance if sheet_type == 'bot' else self.my_performance
            
            all_records = worksheet.get_all_records()
            
            today_closed = [r for r in all_records 
                           if r.get('Exit_Date', '').startswith(today) and r.get('Status') != 'OPEN']
            
            if not today_closed:
                return
            
            wins = [r for r in today_closed if r.get('PnL_Dollar', 0) > 0]
            losses = [r for r in today_closed if r.get('PnL_Dollar', 0) <= 0]
            
            gross_profit = sum(r.get('PnL_Dollar', 0) for r in wins)
            gross_loss = sum(r.get('PnL_Dollar', 0) for r in losses)
            
            row = [
                today, 
                len(today_closed), 
                len(wins), 
                len(losses),
                f"{len(wins)/len(today_closed)*100:.1f}%" if today_closed else "0%",
                f"${gross_profit:.2f}", 
                f"${gross_loss:.2f}",
                f"${gross_profit + gross_loss:.2f}"
            ]
            
            dates = perf_sheet.col_values(1)
            if today in dates:
                row_num = dates.index(today) + 1
                perf_sheet.update(f'A{row_num}:H{row_num}', [row])
            else:
                perf_sheet.append_row(row)
            
            time.sleep(1)  # Rate limit protection
            
        except Exception as e:
            print(f"  ❌ Error updating performance: {e}")
