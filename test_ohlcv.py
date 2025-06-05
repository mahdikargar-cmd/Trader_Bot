import requests
import time
import hmac
import hashlib
import os
from dotenv import load_dotenv

# بارگذاری API Key
load_dotenv()
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')

def generate_signature(timestamp, recv_window, params):
    param_str = f"{timestamp}{api_key}{recv_window}{params}"
    return hmac.new(api_secret.encode('utf-8'), param_str.encode('utf-8'), hashlib.sha256).hexdigest()

# تنظیمات درخواست
url = 'https://api-demo.bybit.com/v5/market/kline'
timestamp = str(int(time.time() * 1000))
recv_window = '5000'
params = 'category=linear&symbol=ETHUSDT&interval=15&limit=100'

# محاسبه امضا
signature = generate_signature(timestamp, recv_window, params)

# هدرها
headers = {
    'X-BAPI-API-KEY': api_key,
    'X-BAPI-TIMESTAMP': timestamp,
    'X-BAPI-RECV-WINDOW': recv_window,
    'X-BAPI-SIGN': signature,
}

# ارسال درخواست
response = requests.get(url, headers=headers, params={
    'category': 'linear',
    'symbol': 'ETHUSDT',
    'interval': '15',
    'limit': '100'
})
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")