import requests
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"

r = requests.get(url)
print(r.text)
