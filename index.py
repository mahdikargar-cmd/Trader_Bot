import ccxt
import time
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
import logging
import os
from dotenv import load_dotenv
import uuid

# تنظیم لاگ با جزئیات کامل
logging.basicConfig(
    filename='trading_bot_detailed.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# بارگذاری کلیدهای API از فایل .env
load_dotenv()
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')
if not api_key or not api_secret:
    logging.error("API key or secret not found in environment variables")
    raise ValueError("API key or secret not found")

# تنظیمات صرافی
exchange = ccxt.bitunix({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'},
})

symbols = ['ETH/USDT', 'DOT/USDT', 'DOGE/USDT', 'XRP/USDT']
timeframe = '15m'
base_risk_percent = 0.20  # ریسک پایه 20%
leverage = 5
max_open_positions = 2
position_value = 20  # ارزش پوزیشن 20 دلار (4 دلار ریسک با اهرم 5x)
min_order_sizes = {
    'ETH/USDT': 0.004,  # ~10 دلار با قیمت 2500 دلار
    'DOT/USDT': 1.0,    # ~5 دلار با قیمت 5 دلار
    'DOGE/USDT': 60.0,  # ~6 دلار با قیمت 0.1 دلار
    'XRP/USDT': 2.0     # ~1 دلار با قیمت 0.5 دلار
}

def fetch_ohlcv_with_retry(symbol, max_retries=3):
    for i in range(max_retries):
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
            logging.info(f"[OHLCV] Successfully fetched OHLCV data for {symbol}: {len(data)} candles")
            return data
        except Exception as e:
            logging.error(f"[OHLCV] Retry {i+1}/{max_retries} for {symbol}: {str(e)}")
            time.sleep(2 ** i)
    logging.error(f"[OHLCV] Failed to fetch OHLCV data for {symbol}, continuing to next cycle")
    return None

def find_support_resistance(df, window=20):
    resistance = df['high'].rolling(window=window).max().shift(1).iloc[-1]
    support = df['low'].rolling(window=window).min().shift(1).iloc[-1]
    logging.info(f"[S/R] Support: {support:.2f}, Resistance: {resistance:.2f}")
    return support, resistance

def adjust_risk_percent(atr, adx, price, base_risk=0.20):
    atr_normalized = atr / price
    if atr_normalized > 0.02:
        risk = base_risk * 0.5
    elif adx < 20:
        risk = base_risk * 0.75
    else:
        risk = base_risk
    logging.info(f"[RISK] Adjusted risk: {risk*100:.1f}% (ATR: {atr:.2f}, ADX: {adx:.2f})")
    return risk

def generate_signal(df, symbol):
    df['ema_short'] = EMAIndicator(df['close'], window=12).ema_indicator()
    df['ema_long'] = EMAIndicator(df['close'], window=26).ema_indicator()
    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close'], window=14).adx()
    df['atr'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    logging.info(f"[INDICATORS] {symbol} - EMA12: {last['ema_short']:.2f}, EMA26: {last['ema_long']:.2f}, "
                 f"RSI: {last['rsi']:.2f}, ADX: {last['adx']:.2f}, ATR: {last['atr']:.2f}")

    if (last['ema_short'] > last['ema_long'] and prev['ema_short'] <= prev['ema_long'] 
        and last['rsi'] < 40 and last['adx'] > 20):
        return {'signal': 'buy', 'adx': last['adx'], 'atr': last['atr'], 'price': last['close'], 'rsi': last['rsi']}
    elif (last['ema_short'] < last['ema_long'] and prev['ema_short'] >= prev['ema_long'] 
          and last['rsi'] > 60 and last['adx'] > 20):
        return {'signal': 'sell', 'adx': last['adx'], 'atr': last['atr'], 'price': last['close'], 'rsi': last['rsi']}
    return None

def get_balance():
    try:
        balance = exchange.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        logging.info(f"[BALANCE] Total USDT: {usdt_balance:.2f}")
        return usdt_balance
    except Exception as e:
        logging.error(f"[BALANCE] Error fetching balance: {str(e)}")
        return 0

def get_position_size(price, symbol):
    position_size = position_value / price
    position_size = max(min_order_sizes.get(symbol, 0.001), round(position_size, 4))
    logging.info(f"[SIZE] Position size for {symbol}: {position_size:.4f}, Value: {position_size * price:.2f} USDT")
    return position_size

def count_open_positions():
    try:
        positions = exchange.fetch_positions(symbols)
        open_positions = sum(1 for pos in positions if pos['amount'] != 0)
        logging.info(f"[POSITIONS] Total open positions: {open_positions}")
        return open_positions
    except Exception as e:
        logging.error(f"[POSITIONS] Error checking positions: {str(e)}")
        return 0

def has_open_position(symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if pos['amount'] != 0:
                logging.info(f"[POSITION] Open position for {symbol}: {pos['side']} (Amount: {pos['amount']:.4f}, PositionId: {pos.get('id', 'N/A')})")
                return pos['side'].lower(), pos.get('id')
        logging.info(f"[POSITION] No open positions for {symbol}")
        return None, None
    except Exception as e:
        logging.error(f"[POSITION] Error checking positions for {symbol}: {str(e)}")
        return None, None

def calculate_take_profits(price, atr, support, resistance, signal):
    if signal == 'buy':
        sl_price = price - atr
        tp_price = price + 2 * atr
        tp2_price = min(tp_price, resistance * 0.995)
    else:
        sl_price = price + atr
        tp_price = price - 2 * atr
        tp2_price = max(tp_price, support * 1.005)
    
    logging.info(f"[TP/SL] TP: {tp_price:.2f}, TP2: {tp2_price:.2f}, SL: {sl_price:.2f}")
    return sl_price, tp_price, tp2_price

def place_order(symbol, signal, price, atr, adx, support, resistance):
    if count_open_positions() >= max_open_positions:
        logging.info(f"[ORDER] Max open positions ({max_open_positions}) reached, skipping order for {symbol}")
        return None

    current_position, position_id = has_open_position(symbol)
    if current_position:
        if (signal == 'buy' and current_position == 'long') or (signal == 'sell' and current_position == 'short'):
            logging.info(f"[ORDER] Position already open in same direction for {symbol}, skipping.")
            return None
        elif (signal == 'buy' and current_position == 'short') or (signal == 'sell' and current_position == 'long'):
            logging.info(f"[ORDER] Closing opposite position for {symbol} before opening new one.")
            try:
                if position_id:
                    exchange.request('POST', '/api/v1/futures/trade/flash_close_position', {'positionId': position_id})
                else:
                    exchange.request('POST', '/api/v1/futures/trade/close_all_position', {'symbol': symbol.replace('/', '')})
                time.sleep(1)
            except Exception as e:
                logging.error(f"[ORDER] Failed to close position for {symbol}: {str(e)}")
                return None

    balance = get_balance()
    if balance < 4:  # حداقل 4 دلار برای ریسک
        logging.error(f"[ORDER] Insufficient balance for {symbol}: {balance:.2f} USDT")
        return None

    amount = get_position_size(price, symbol)
    sl_price, tp_price, tp2_price = calculate_take_profits(price, atr, support, resistance, signal)

    try:
        order_list = [
            {
                'side': 'BUY' if signal == 'buy' else 'SELL',
                'qty': str(amount),
                'orderType': 'MARKET',
                'tradeSide': 'OPEN',
                'reduceOnly': False,
                'clientId': str(uuid.uuid4()),
                'tpPrice': str(tp_price),
                'tpStopType': 'MARK_PRICE',
                'tpOrderType': 'LIMIT',
                'tpOrderPrice': str(tp_price),
                'slPrice': str(sl_price),
                'slStopType': 'MARK_PRICE',
                'slOrderType': 'MARKET'
            },
            {
                'side': 'SELL' if signal == 'buy' else 'BUY',
                'qty': str(amount * 0.5),
                'price': str(tp2_price),
                'orderType': 'LIMIT',
                'tradeSide': 'CLOSE',
                'reduceOnly': True,
                'effect': 'GTC',
                'clientId': str(uuid.uuid4())
            }
        ]

        response = exchange.request('POST', '/api/v1/futures/trade/batch_order', {
            'symbol': symbol.replace('/', ''),
            'orderList': order_list
        })

        logging.info(f"[ORDER] {signal.upper()} for {symbol} - Size: {amount:.4f}, Entry: {price:.2f}, "
                     f"TP1: {tp_price:.2f}, TP2: {tp2_price:.2f}, SL: {sl_price:.2f}, "
                     f"Balance: {balance:.2f} USDT, Response: {response}")
        return response
    except Exception as e:
        logging.error(f"[ORDER] Failed to place order for {symbol}: {str(e)}")
        return None

def select_best_signals():
    signals = []
    for symbol in symbols:
        try:
            ohlcv = fetch_ohlcv_with_retry(symbol)
            if ohlcv is None:
                continue

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            signal_data = generate_signal(df, symbol)
            if signal_data:
                signal_data['symbol'] = symbol
                signal_data['support'], signal_data['resistance'] = find_support_resistance(df)
                signals.append(signal_data)
        except Exception as e:
            logging.error(f"[ERROR] {symbol}: {str(e)}")

    # مرتب‌سازی سیگنال‌ها بر اساس ADX (روند قوی‌تر) و ATR نرمال‌شده (ریسک کمتر)
    signals.sort(key=lambda x: (-x['adx'], x['atr'] / x['price']))
    
    # انتخاب حداکثر دو سیگنال برتر
    return signals[:max_open_positions]

def sync_with_candle():
    current_time = time.time()
    candle_duration = 15 * 60
    sleep_time = candle_duration - (current_time % candle_duration)
    logging.info(f"[SYNC] Waiting {sleep_time:.0f}s for next candle")
    time.sleep(sleep_time)

def run_bot():
    try:
        for symbol in symbols:
            exchange.set_leverage(leverage, symbol)
            logging.info(f"[INIT] Leverage set to {leverage}x for {symbol}")
    except Exception as e:
        logging.error(f"[INIT] Failed to set leverage: {str(e)}")
        return

    while True:
        sync_with_candle()
        try:
            best_signals = select_best_signals()
            if not best_signals:
                logging.info("[WAITING] No valid signals for any symbol.")
                continue

            for signal_data in best_signals:
                symbol = signal_data['symbol']
                signal = signal_data['signal']
                price = signal_data['price']
                atr = signal_data['atr']
                adx = signal_data['adx']
                support = signal_data['support']
                resistance = signal_data['resistance']

                logging.info(f"[SIGNAL] {signal.upper()} for {symbol} at {price:.2f} (ADX: {adx:.2f}, ATR: {atr:.2f})")
                place_order(symbol, signal, price, atr, adx, support, resistance)

        except Exception as e:
            logging.error(f"[ERROR] Main loop: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()