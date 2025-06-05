import requests
import hmac
import hashlib
import time
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')

def generate_signature(api_secret, timestamp, recv_window, payload):
    param_str = f"{timestamp}{api_key}{recv_window}{payload}"
    return hmac.new(api_secret.encode('utf-8'), param_str.encode('utf-8'), hashlib.sha256).hexdigest()

url = 'https://api-demo.bybit.com/v5/account/demo-apply-money'
timestamp = str(int(time.time() * 1000))
recv_window = '5000'
payload = '{"adjustType":0,"utaDemoApplyMoney":[{"coin":"USDT","amountStr":"100000"},{"coin":"ETH","amountStr":"1"}]}'

signature = generate_signature(api_secret, timestamp, recv_window, payload)

headers = {
    'X-BAPI-API-KEY': api_key,
    'X-BAPI-TIMESTAMP': timestamp,
    'X-BAPI-RECV-WINDOW': recv_window,
    'X-BAPI-SIGN': signature,
    'Content-Type': 'application/json',
}

response = requests.post(url, headers=headers, data=payload)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")