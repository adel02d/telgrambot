import os
import telebot
import requests
import sqlite3
import time
import threading
from flask import Flask

# --- 1. CONFIGURACIÓN ---
TOKEN_TELEGRAM = os.environ.get('TOKEN_TELEGRAM')
API_KEY_ODDS = os.environ.get('API_KEY_ODDS')

if not TOKEN_TELEGRAM or not API_KEY_ODDS:
    print("❌ ERROR: Faltan las variables de entorno TOKEN_TELEGRAM o API_KEY_ODDS.")
    exit()

bot = telebot.TeleBot(TOKEN_TELEGRAM)
bot.delete_webhook() # Limpieza inicial

# --- SERVIDOR WEB ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Activo y Escaneando 🤖"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- 2. CONFIGURACIÓN API Y DEPORTES ---
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports"
SPORTS_MAP = ['soccer', 'basketball_euroleague', 'basketball_nba'] 
REGIONS = 'eu'
MARKETS = 'h2h'

# --- 3. BASE DE DATOS (BLINDAJE PARA THREADING) ---
# Importante: check_same_thread=False para evitar bloqueos entre bot y servidor web
def init_db():
    conn = sqlite3.connect('real_trading.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            balance REAL DEFAULT 1000.00,
            active_scan INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user(chat_id):
    conn = sqlite3.connect('real_trading.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE chat_id = ?", (str(chat_id),))
    user = cursor.fetchone()
    conn.close()
    if not user: return None
    return {'chat_id': user[0], 'balance': user[1], 'active_scan': bool(user[2])}

def create_user(chat_id):
    conn = sqlite3.connect('real_trading.db', check_same_thread=False)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (chat_id) VALUES (?)", (str(chat_id),))
        conn.commit()
    except: pass
    conn.close()

def update_user_balance(chat_id, amount):
    conn = sqlite3.connect('real_trading.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (amount, str(chat_id)))
    conn.commit()
    conn.close()

def toggle_scan(chat_id, status):
    conn = sqlite3.connect('real_trading.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET active_scan = ? WHERE chat_id = ?", (1 if status else 0, str(chat_id)))
    conn.commit()
    conn.close()

# --- 4. LÓGICA DE ESCANEO ---
def fetch_odds():
    all_games = []
    headers = {'Content-Type': 'application/json'}
    
    for sport in SPORTS_MAP:
        try:
            url = f"{ODDS_API_URL}/{sport}/odds-live"
            params = {
                'apiKey': API_KEY_ODDS,
                'regions': REGIONS,
                'markets': MARKETS,
                'oddsFormat': 'decimal'
            }
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                all_games.extend(response.json())
        except Exception as e:
            print(f"Error API: {e}")
    return all_games

def scan_loop():
    print("🚀 Escáner iniciado (cada 10 min)...")
    notified = set()
    
    while True:
        try:
            conn = sqlite3.connect('real_trading.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM users WHERE active_scan = 1")
            users = [x[0] for x in cursor.fetchall()]
            conn.close()

            if users:
                games = fetch_odds()
                print(f"🔍 Analizando {len(games)} partidos...")
                
                for game in games:
                    sport = '⚽' if 'soccer' in game['sport_key'] else '🏀'
                    home = game['home_team']
                    away = game['away_team']
                    
                    for bookmaker in game.get('bookmakers', []):
                        for market in bookmaker.get('markets', []):
                            for outcome in market.get('outcomes', []):
                                price = outcome['price']
                                if price >= 1.90:
                                    gid = f"{game['id']}_{bookmaker['key']}_{outcome['name']}"
                                    if gid not in notified:
                                        notified.add(gid)
                                        if len(notified) > 500: notified.clear() # Memoria
                                        for uid in users:
                                            try:
                                                bot.send_message(uid, 
                                                    f"🔔 <b>{sport} LIVE</b>\n{home} vs {away}\n"
                                                    f"🎯 {outcome['name']} @ {price}\n"
                                                    f"🏢 {bookmaker['title']}", parse_mode='HTML')
                                            except: pass
        except Exception as e:
            print(f"⚠️ Error en escáner: {e}")
        
        print("✅ Esperando 10 minutos...")
        time.sleep(600)

# --- 5. COMANDOS ---
@bot.message_handler(commands=['start'])
def cmd_start(m):
    create_user(m.chat.id)
    bot.send_message(m.chat.id, "✅ Bot iniciado. Usa /scan para empezar.")

@bot.message_handler(commands=['scan'])
def cmd_scan(m):
    create_user(m.chat.id)
    toggle_scan(m.chat.id, True)
    bot.send_message(m.chat.id, "📡 <b>Escáner ACTIVO.</b>\nRevisando mercados cada 10 minutos.", parse_mode='HTML')

@bot.message_handler(commands=['stop'])
def cmd_stop(m):
    toggle_scan(m.chat.id, False)
    bot.send_message(m.chat.id, "🛑 Escáner apagado.")

@bot.message_handler(commands=['balance'])
def cmd_balance(m):
    user = get_user(m.chat.id)
    if user:
        bot.send_message(m.chat.id, f"💳 Saldo: {user['balance']:.2f}€")
    else:
        bot.send_message(m.chat.id, "Usa /start primero.")

# --- 6. EJECUCIÓN (BLINDAJE ANTI-CRASH) ---

def run_telegram_bot():
    while True: # Bucle infinito: si se cae, se levanta solo
        try:
            print("🤖 Bot de Telegram iniciado.")
            bot.infinity_polling(timeout=10, long_polling_timeout=20)
        except Exception as e:
            print(f"❌ Bot caído. Reiniciando en 5s... Error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    init_db()
    
    # Thread Escáner
    t1 = threading.Thread(target=scan_loop)
    t1.daemon = True
    t1.start()
    
    # Thread Telegram
    t2 = threading.Thread(target=run_telegram_bot)
    t2.daemon = True
    t2.start()
    
    # Main: Flask
    print("🌐 Servidor Web corriendo...")
    run_flask()
