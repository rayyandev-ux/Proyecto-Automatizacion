import requests
import os

class TelegramNotifier:
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        
    def send_deal_alert(self, car_data: dict, analysis: dict) -> bool:
        if not self.bot_token or not self.chat_id:
            print("Telegram credentials not configured.")
            return False
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        message = f"🚗 *NUEVA BUENA OFERTA ENCONTRADA*\n\n"
        message += f"📌 *Título:* {car_data.get('title')}\n"
        message += f"💰 *Precio Publicado:* {car_data.get('price')}\n"
        message += f"📊 *Precio Mercado (estimado):* ${analysis.get('precio_mercado_sugerido', 'N/A')}\n"
        message += f"✅ *Por qué es buena oferta:* {analysis.get('observaciones', 'N/A')}\n\n"
        message += f"🔗 *Enlace:* {car_data.get('url')}"
        
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")
            return False
