import ccxt
import time
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
import logging
import os
from dotenv import load_dotenv
import requests
import hmac
import hashlib
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# تنظیمات لاگ
logging.basicConfig(
    filename='trading_bot_detailed.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# بارگذاری API Key
load_dotenv()
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')
if not api_key or not api_secret:
    logging.error("API key or secret not found")
    raise ValueError("API key or secret not found")

# تنظیمات صرافی Bybit Demo
exchange = ccxt.bybit({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'urls': {
        'https://api-demo.bybit.com',
    },
    'options': {
        'defaultType': 'linear',
        'adjustForTimeDifference': True,
    },
})

symbols = ['ETHUSDT']
timeframe = '15m'
base_risk_percent = 0.20
leverage = 5
max_open_positions = 2
position_value = 20
min_order_sizes = {
    'ETHUSDT': 0.004,
}

def generate_signature(timestamp, recv_window, payload):
    param_str = f"{timestamp}{api_key}{recv_window}{payload}"
    return hmac.new(api_secret.encode('utf-8'), param_str.encode('utf-8'), hashlib.sha256).hexdigest()

def set_leverage_with_requests(symbol):
    try:
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        url = 'https://api-demo.bybit.com/v5/position/set-leverage'
        timestamp = str(int(time.time() * 1000))
        recv_window = '5000'
        payload = json.dumps({
            'category': 'linear',
            'symbol': symbol,
            'buyLeverage': str(leverage),
            'sellLeverage': str(leverage)
        })

        headers = {
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'X-BAPI-SIGN': generate_signature(timestamp, recv_window, payload),
            'Content-Type': 'application/json',
        }

        response = session.post(url, headers=headers, data=payload)
        response_json = response.json()
        logging.info(f"[INIT] Leverage response for {symbol}: {response_json}")
        if response_json.get('retCode') == 0:
            logging.info(f"[INIT] Leverage set to {leverage}x for {symbol}")
        elif response_json.get('retCode') == 110043:
            logging.info(f"[INIT] Leverage for {symbol} already set to {leverage}x (no modification needed)")
        else:
            logging.error(f"[INIT] Failed to set leverage for {symbol}: {response_json.get('retMsg')}")
    except Exception as e:
        logging.error(f"[INIT] Error setting leverage for {symbol}: {str(e)}")

def request_demo_funds_with_requests():
    try:
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        url = 'https://api-demo.bybit.com/v5/account/demo-apply-money'
        timestamp = str(int(time.time() * 1000))
        recv_window = '5000'
        payload = json.dumps({
            'adjustType': 0,
            'utaDemoApplyMoney': [
                {'coin': 'USDT', 'amountStr': '100000'},
                {'coin': 'ETH', 'amountStr': '1'},
            ]
        })

        headers = {
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'X-BAPI-SIGN': generate_signature(timestamp, recv_window, payload),
            'Content-Type': 'application/json',
        }

        response = session.post(url, headers=headers, data=payload)
        response_json = response.json()
        logging.info(f"[FUNDS] Demo funds response: {response_json}")
        if response_json.get('retCode') == 0:
            logging.info("[FUNDS] Requested demo funds successfully")
        else:
            logging.error(f"[FUNDS] Failed to request demo funds: {response_json.get('retMsg')}")
    except Exception as e:
        logging.error(f"[FUNDS] Error requesting demo funds: {str(e)}")

def fetch_ohlcv_with_retry(symbol, max_retries=5):
    for i in range(max_retries):
        try:
            session = requests.Session()
            retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
            session.mount('https://', HTTPAdapter(max_retries=retries))

            url = 'https://api-demo.bybit.com/v5/market/kline'
            timestamp = str(int(time.time() * 1000))
            recv_window = '5000'
            params = f"category=linear&symbol={symbol}&interval={timeframe}&limit=100"
            signature = generate_signature(timestamp, recv_window, params)

            headers = {
                'X-BAPI-API-KEY': api_key,
                'X-BAPI-TIMESTAMP': timestamp,
                'X-BAPI-RECV-WINDOW': recv_window,
                'X-BAPI-SIGN': signature,
            }

            response = session.get(url, headers=headers, params={
                'category': 'linear',
                'symbol': symbol,
                'interval': timeframe,
                'limit': '100'
            })

            response_json = response.json()
            logging.info(f"[OHLCV] Raw response for {symbol}: {response_json}")

            if response_json.get('retCode') != 0:
                logging.error(f"[OHLCV] Failed to fetch OHLCV for {symbol}: {response_json.get('retMsg')}")
                time.sleep(2 ** i)
                continue

            candles = response_json['result']['list']
            # تبدیل داده‌ها به فرمت CCXT: [timestamp, open, high, low, close, volume]
            data = [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in candles]
            logging.info(f"[OHLCV] Fetched OHLCV for {symbol}: {len(data)} candles")
            return data
        except Exception as e:
            logging.error(f"[OHLCV] Retry {i+1}/{max_retries} for {symbol}: {str(e)}")
            time.sleep(2 ** i)
    logging.error(f"[OHLCV] Failed to fetch OHLCV for {symbol}")
    return None

def find_support_resistance(df, window=20):
    resistance = df['high'].rolling(window=window).max().shift(1).iloc[-1]
    support = df['low'].rolling(window=window).min().shift(1).iloc[-1]
    logging.info(f"[S/R] Support: {support:.2f}, Resistance: {resistance:.2f}")
    return support, resistance

def adjust_risk_percent(atr, adx, price, symbol, base_risk=0.20):
    atr_normalized = atr / price
    if atr_normalized > 0.02 or 'DOGE' in symbol:
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

def get_position_size(price, symbol, risk_percent):
    risk_amount = 20 * risk_percent
    position_size = position_value / price
    position_size = max(min_order_sizes.get(symbol, 0.001), round(position_size, 4))
    logging.info(f"[SIZE] Position size for {symbol}: {position_size:.4f}, Value: {position_size * price:.2f} USDT, Risk: {risk_amount:.2f}")
    return position_size

def count_open_positions():
    try:
        positions = exchange.fetch_positions(symbols)
        open_positions = sum(1 for pos in positions if abs(pos['contracts']) > 0)
        logging.info(f"[POSITIONS] Total open positions: {open_positions}")
        return open_positions
    except Exception as e:
        logging.error(f"[POSITIONS] Error checking positions: {str(e)}")
        return 0

def has_open_position(symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if abs(pos['contracts']) > 0:
                logging.info(f"[POSITION] Open position for {symbol}: {pos['side']} (Amount: {pos['contracts']:.4f})")
                return pos['side'].lower(), pos.get('id')
        logging.info(f"[POSITION] No open positions for {symbol}")
        return None, None
    except Exception as e:
        logging.error(f"[POSITION] Error checking positions for {symbol}: {str(e)}")
        return None, None

def calculate_take_profits(price, atr, support, resistance, signal):
    if signal == 'buy':
        sl_price = price - 1.2 * atr
        tp_price = price + 2 * atr
        tp2_price = min(tp_price, resistance * 0.95)
    else:
        sl_price = price + 1.2 * atr
        tp_price = price - 2 * atr
        tp2_price = max(tp_price, support * 1.05)
    
    logging.info(f"[TP/SL] TP: {tp_price:.2f}, TP2: {tp2_price:.2f}, SL: {sl_price:.2f}")
    return sl_price, tp_price, tp2_price

def place_order(symbol, signal, price, atr, adx, support, resistance):
    if count_open_positions() >= max_open_positions:
        logging.info(f"[ORDER] Max open positions reached, skipping order for {symbol}")
        return None

    current_position, position_id = has_open_position(symbol)
    if current_position:
        if (signal == 'buy' and current_position == 'long') or (signal == 'sell' and current_position == 'short'):
            logging.info(f"[ORDER] Position already open in same direction for {symbol}, skipping.")
            return None
        elif (signal == 'buy' and current_position == 'short') or (signal == 'sell' and current_position == 'long'):
            logging.info(f"[ORDER] Closing opposite position for {symbol} before opening new one.")
            try:
                exchange.create_market_order(symbol, 'buy' if current_position == 'short' else 'sell', None, params={'reduceOnly': True})
                time.sleep(2)
            except Exception as e:
                logging.error(f"[ORDER] Failed to close position for {symbol}: {str(e)}")
                return None

    balance = get_balance()
    risk_percent = adjust_risk_percent(atr, adx, price, symbol)
    if balance < risk_percent * 20:
        logging.error(f"[ORDER] Insufficient balance for {symbol}: {balance:.2f} USDT")
        return None

    amount = get_position_size(price, symbol, risk_percent)
    sl_price, tp_price, tp2_price = calculate_take_profits(price, atr, support, resistance, signal)

    try:
        order = exchange.create_market_order(
            symbol=symbol,
            side=signal,
            amount=amount,
            params={
                'category': 'linear',
                'stopLossPrice': str(sl_price),
                'takeProfitPrice': str(tp_price),
                'stopLoss': 'MARKET',
                'takeProfit': 'LIMIT',
            }
        )

        close_side = 'sell' if signal == 'buy' else 'buy'
        close_order = exchange.create_limit_order(
            symbol=symbol,
            side=close_side,
            amount=amount * 0.5,
            price=tp2_price,
            params={
                'category': 'linear',
                'reduceOnly': True,
            }
        )

        logging.info(f"[ORDER] {signal.upper()} {symbol} - Size: {amount:.4f}, Entry: {price:.2f}, "
                     f"TP1: {tp_price:.2f}, TP2: {tp2_price:.2f}, SL: {sl_price:.2f}, "
                     f"Balance: {balance:.2f} USDT, Order: {order}, CloseOrder: {close_order}")
        return order, close_order
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

    signals.sort(key=lambda x: (-x['adx'], x['atr'] / x['price']))
    return signals[:max_open_positions]

def sync_with_candle():
    current_time = time.time()
    candle_duration = 15 * 60
    sleep_time = candle_duration - (current_time % candle_duration)
    logging.info(f"[SYNC] Waiting {sleep_time:.0f}s for next candle")
    time.sleep(sleep_time)

def run_bot():
    for symbol in symbols:
        set_leverage_with_requests(symbol)

    request_demo_funds_with_requests()

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