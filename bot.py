import logging
import json
import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = 'TU_TOKEN_TELEGRAM_AQUI' # <--- PON TU TOKEN AQUÍ
ODDS_API_KEY = 'TU_API_KEY_DE_CUOTAS_AQUI' # <--- PON TU API KEY AQUÍ

DATA_FILE = 'bot_data.json'

# ÚNICAMENTE las 3 ligas solicitadas
LEAGUES_TO_SCAN = [
    'soccer_epl',             # Premier League (Inglaterra)
    'soccer_spain_la_liga',   # La Liga (España)
    'soccer_germany_bundesliga1' # Bundesliga (Alemania)
]

# Configuración de Logs
logging.basicConfig(level=logging.INFO)

# --- GESTIÓN DE DATOS (Persistencia en Archivo) ---
def load_data():
    default_data = {
        "balance": 1000.00,
        "total_deposited": 1000.00,
        "total_withdrawn": 0.00,
        "history": [],
        "bot_stats": {
            "bets_sent": 0,
            "accepted": 0,
            "rejected": 0,
            "wins": 0,
            "losses": 0
        },
        "current_signal": None # Para guardar la señal activa pendiente de aceptación
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return default_data
    return default_data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- TECLADOS (MENÚS INTERACTIVOS) ---

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Depósito / Balance", callback_data='menu_deposit')],
        [InlineKeyboardButton("🎲 Mis Apuestas", callback_data='menu_bets')],
        [InlineKeyboardButton("🤖 Estadísticas Bot", callback_data='menu_bot')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_deposit_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Depositar $100", callback_data='action_deposit_100')],
        [InlineKeyboardButton("➖ Retirar $100", callback_data='action_withdraw_100')],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_bet_actions_menu(bet_index):
    keyboard = [
        [InlineKeyboardButton("✅ Marcar como GANADA", callback_data=f'result_win_{bet_index}')],
        [InlineKeyboardButton("❌ Marcar como PERDIDA", callback_data=f'result_loss_{bet_index}')],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_menu():
    keyboard = [[InlineKeyboardButton("🔙 Volver al Menú", callback_data='menu_main')]]
    return InlineKeyboardMarkup(keyboard)

# --- LÓGICA DE NEGOCIO ---

def calculate_profit(odds, stake):
    return stake * (odds - 1)

async def send_main_menu(update, context, text="🏠 *MENÚ PRINCIPAL*"):
    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=get_main_menu())
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_menu())

async def show_deposit_menu(update, context):
    data = load_data()
    profit = data['balance'] - (data['total_deposited'] - data['total_withdrawn'])
    
    text = (
        f"💰 *BANCA VIRTUAL*\n\n"
        f"Saldo Actual: ${data['balance']:.2f}\n"
        f"Total Depositado: ${data['total_deposited']:.2f}\n"
        f"Total Retirado: ${data['total_withdrawn']:.2f}\n"
        f"Profit Neto: ${profit:.2f}\n\n"
        f"Usa los botones para gestionar fondos:"
    )
    await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=get_deposit_menu())

async def handle_deposit_actions(update, context):
    query = update.callback_query
    await query.answer()
    data = load_data()
    action = query.data
    
    if 'deposit' in action:
        amount = 100
        data['balance'] += amount
        data['total_deposited'] += amount
        msg = f"✅ Depositados ${amount}. Nuevo saldo: ${data['balance']}"
    elif 'withdraw' in action:
        amount = 100
        if data['balance'] >= amount:
            data['balance'] -= amount
            data['total_withdrawn'] += amount
            msg = f"✅ Retirados ${amount}. Nuevo saldo: ${data['balance']}"
        else:
            msg = f"❌ Fondos insuficientes para retirar."
    
    save_data(data)
    await show_deposit_menu(update, context)

async def show_bets_menu(update, context):
    data = load_data()
    if not data['history']:
        text = "📭 No hay apuestas registradas aún."
        await update.callback_query.message.edit_text(text, reply_markup=get_back_menu())
        return

    text = "📜 *HISTORIAL DE APUESTAS (Últimas 5)*\n\n"
    for i, bet in enumerate(reversed(data['history'][-5:])):
        real_idx = len(data['history'] - 1 - i
        status_icon = "⏳" if bet['status'] == 'Pending' else ("✅" if bet['status'] == 'Win' else "❌")
        text += f"{status_icon} *{bet['match']}*\n"
        text += f"   Apuesta: ${bet['stake']} | Cuota: {bet['odds']}\n"
        text += f"   Resultado: {bet['status']}\n\n"

    if data['history'] and data['history'][-1]['status'] == 'Pending':
        last_idx = len(data['history']) - 1
        text += "Gestiona tu última apuesta pendiente abajo:"
        await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=get_bet_actions_menu(last_idx))
    else:
        await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=get_back_menu())

async def handle_bet_result(update, context):
    query = update.callback_query
    await query.answer()
    data = load_data()
    
    parts = query.data.split('_')
    result = parts[1] 
    bet_index = int(parts[2])
    
    if 0 <= bet_index < len(data['history']):
        bet = data['history'][bet_index]
        if bet['status'] == 'Pending':
            bet['status'] = 'Win' if result == 'win' else 'Loss'
            
            if result == 'win':
                profit = calculate_profit(bet['odds'], bet['stake'])
                data['balance'] += (bet['stake'] + profit)
                data['bot_stats']['wins'] += 1
                msg = f"🎉 ¡Ganaste! Profit: ${profit:.2f}"
            else:
                data['bot_stats']['losses'] += 1
                msg = f"📉 Perdiste. Stake: ${bet['stake']}"
            
            save_data(data)
            await update.callback_query.message.reply_text(msg)
            await send_main_menu(update, context, "Estado actualizado.")

async def show_bot_stats(update, context):
    data = load_data()
    stats = data['bot_stats']
    total_resolved = stats['wins'] + stats['losses']
    avg = 0
    if total_resolved > 0:
        avg = (stats['wins'] / total_resolved) * 100
        
    text = (
        f"🤖 *ESTADÍSTICAS DEL BOT*\n\n"
        f"Señales Enviadas: {stats['bets_sent']}\n"
        f"Aceptadas por ti: {stats['accepted']}\n"
        f"Rechazadas: {stats['rejected']}\n\n"
        f"--- RESULTADOS REALES ---\n"
        f"Partidos Ganados: {stats['wins']}\n"
        f"Partidos Perdidos: {stats['losses']}\n"
        f"Promedio de Acierto: {avg:.1f}%\n"
    )
    await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=get_back_menu())

# --- MANEJO DE LA SEÑAL ---

async def handle_signal_response(update, context):
    query = update.callback_query
    await query.answer()
    data = load_data()
    action = query.data
    
    if not data['current_signal']:
        await query.message.reply_text("Esta señal ya expiró o fue gestionada.")
        return

    signal = data['current_signal']
    
    if action == 'accept_bet':
        stake = signal['stake']
        if data['balance'] < stake:
            await query.message.reply_text("❌ Saldo insuficiente para aceptar esta apuesta.")
            return
            
        data['balance'] -= stake
        data['bot_stats']['accepted'] += 1
        
        new_bet = {
            "match": signal['match'],
            "selection": signal['selection'],
            "odds": signal['odds'],
            "stake": stake,
            "status": "Pending",
            "profit_expected": signal['profit']
        }
        data['history'].append(new_bet)
        
        save_data(data)
        await query.message.reply_text(f"✅ *APUESTA ACEPTADA*\n\nStake descontado: ${stake}\nRecuerda ir a 'Mis Apuestas' para marcar el resultado.", parse_mode='Markdown')
        
    elif action == 'reject_bet':
        data['bot_stats']['rejected'] += 1
        save_data(data)
        await query.message.reply_text("❌ Apuesta rechazada. El bot seguirá escaneando.")
    
    data['current_signal'] = None
    save_data(data)

# --- ESCÁNER FÚTBOL (SOLO LAS 3 LIGAS) ---

async def scan_market_job(context: ContextTypes.DEFAULT_TYPE):
    """Escanea Premier, La Liga y Bundesliga."""
    data = load_data()
    
    if data['current_signal']:
        return

    print(f"⚽ Escaneando Fútbol: Premier, La Liga, Bundesliga...")
    
    signal_found = False
    
    for sport_key in LEAGUES_TO_SCAN:
        if signal_found: break 

        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'eu', 
                'markets': 'h2h', 
                'oddsFormat': 'decimal'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                games = response.json()
                if not games: continue

                for game in games:
                    if not game['bookmakers']: continue
                    
                    main_bookmaker = game['bookmakers'][0]
                    market = main_bookmaker['markets'][0]
                    
                    for outcome in market['outcomes']:
                        price = outcome['price']
                        
                        # Estrategia: Valor en cuotas entre 1.90 y 2.40
                        if 1.90 <= price <= 2.40:
                            
                            stake = data['balance'] * 0.05
                            if stake < 1: stake = 1 
                            
                            profit = calculate_profit(price, stake)
                            
                            signal = {
                                "match": f"{game['home_team']} vs {game['away_team']}",
                                "selection": outcome['name'],
                                "odds": price,
                                "stake": round(stake, 2),
                                "profit": round(profit, 2)
                            }
                            
                            data['current_signal'] = signal
                            data['bot_stats']['bets_sent'] += 1
                            save_data(data)
                            
                            chat_id = context.job.data
                            keyboard = [
                                [InlineKeyboardButton("✅ ACEPTAR JUGADA", callback_data='accept_bet')],
                                [InlineKeyboardButton("❌ RECHAZAR", callback_data='reject_bet')]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            message = (
                                f"⚽ *OPORTUNIDAD FÚTBOL*\n\n"
                                f"🏟 Liga: {sport_key}\n"
                                f"Partido: {signal['match']}\n"
                                f"🎯 Pronóstico: {signal['selection']}\n"
                                f"💰 Cuota: {signal['odds']}\n"
                                f"💵 Apostar: ${signal['stake']} (5% Banca)\n"
                                f"📈 Ganancia: ${signal['profit']}\n\n"
                                f"¿Aceptas?"
                            )
                            
                            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=reply_markup)
                            print(f"✅ Señal enviada: {signal['match']}")
                            signal_found = True
                            break 
            elif response.status_code == 429:
                print("⚠️ Error 429: Cuota API agotada.")
            else:
                print(f"⚠️ Error API {sport_key}: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error conectando: {e}")

# --- HANDLERS PRINCIPALES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    
    # Intervalo ajustado a 14400 segundos (4 horas)
    # Esto consume aprox 3 ligas * 6 veces al dia = 18 peticiones.
    # 18 * 30 = 540 peticiones al mes (Está en el límite del plan gratis).
    # Si quieres más velocidad, necesitas pagar la API.
    context.job_queue.run_repeating(scan_market_job, interval=14400, first=10, data=chat_id)
    
    await update.message.reply_text(
        "⚽ *BOT TRADER FÚTBOL* INICIADO\n\n"
        "Escaneando únicamente:\n"
        "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League\n"
        "🇪🇸 La Liga\n"
        "🇩🇪 Bundesliga\n\n"
        "Frecuencia: Cada 4 horas (Para no agotar API Gratis).\n"
        "Usa el menú para gestionar tu banca.",
        parse_mode='Markdown',
        reply_markup=get_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == 'menu_main':
        await send_main_menu(update, context)
    elif data == 'menu_deposit':
        await show_deposit_menu(update, context)
    elif 'action_' in data:
        await handle_deposit_actions(update, context)
    elif data == 'menu_bets':
        await show_bets_menu(update, context)
    elif 'result_' in data:
        await handle_bet_result(update, context)
    elif data == 'menu_bot':
        await show_bot_stats(update, context)
    elif 'accept_bet' in data or 'reject_bet' in data:
        await handle_signal_response(update, context)

# --- MAIN ---

def main():
    if 'TU_TOKEN_TELEGRAM_AQUI' in TELEGRAM_TOKEN or 'TU_API_KEY_DE_CUOTAS_AQUI' in ODDS_API_KEY:
        print("⚠️ ERROR: Edita el archivo y pon tus TOKENS reales.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot de Fútbol iniciado. Escaneando Top 3 Ligas...")
    application.run_polling()

if __name__ == '__main__':
    main()
