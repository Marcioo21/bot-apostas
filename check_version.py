# check_version.py
import sys
import telegram

print(f"Python: {sys.version}")
print(f"python-telegram-bot: {telegram.__version__}")

# Verifica compatibilidade
try:
    from telegram.request import HTTPXRequest
    print("✅ HTTPXRequest disponível (versão >= 20.0)")
except ImportError:
    print("⚠️ HTTPXRequest não disponível (versão < 20.0) - usando modo compatível")

# Testa o token
import os
from dotenv import load_dotenv
load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
if token:
    print(f"✅ Token configurado: {token[:10]}...{token[-5:]}")
else:
    print("❌ Token não encontrado no .env")