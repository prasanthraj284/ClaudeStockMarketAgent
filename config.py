"""
Configuration - Handles ALL credentials securely
"""
import os
import json
from pathlib import Path

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass  # dotenv not installed or in cloud - that's ok

# Google Sheets Configuration
SHEET_ID = os.environ.get('SHEET_ID', '1ZiXVVJ5yGXKgbQJhHbLdiw2Z8DYSxKEfTHVwWJwVbhM')

def get_google_creds():
    """Get Google credentials (local file or cloud env var)"""
    # Cloud: environment variable
    creds_json = os.environ.get('GOOGLE_SHEETS_CREDS')
    if creds_json:
        print("🌐 Google Sheets: Using environment variable (cloud mode)")
        return json.loads(creds_json)
    
    # Local: credentials.json file
    if Path('credentials.json').exists():
        print("💻 Google Sheets: Using credentials.json (local mode)")
        with open('credentials.json') as f:
            return json.load(f)
    
    raise Exception("❌ No Google credentials found! Need credentials.json or GOOGLE_SHEETS_CREDS")

def get_telegram_token():
    """Get Telegram bot token from environment variable"""
    token = os.environ.get('TELEGRAM_TOKEN')
    
    if not token:
        raise Exception(
            "❌ No Telegram token found!\n"
            "   Local: Add TELEGRAM_TOKEN to .env file\n"
            "   Cloud: Set TELEGRAM_TOKEN environment variable"
        )
    
    print("✅ Telegram token loaded")
    return token

def get_telegram_chat_id():
    """Get Telegram chat ID from environment variable"""
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not chat_id:
        raise Exception(
            "❌ No Telegram chat ID found!\n"
            "   Local: Add TELEGRAM_CHAT_ID to .env file\n"
            "   Cloud: Set TELEGRAM_CHAT_ID environment variable"
        )
    
    print("✅ Telegram chat ID loaded")
    return chat_id