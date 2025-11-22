import requests
from bs4 import BeautifulSoup
import json
import time
import os
from datetime import datetime
from pathlib import Path
from flask import Flask
import threading


app = Flask(__name__)

@app.route("/")
def home():
    return "SWGOH Bot activo 😎"

def run_web():
    app.run(host="0.0.0.0", port=5000)

threading.Thread(target=run_web).start()

# --- CONFIGURACIÓN ---
FORUM_URL = "https://forums.ea.com/category/star-wars-galaxy-of-heroes-en/blog/swgoh-game-info-hub-en"
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')
CHECK_INTERVAL = 300       # Segundos entre revisiones

SENT_NEWS_FILE = "sent_news.json"

# --- Funciones de registro ---
def load_sent_news():
    if Path(SENT_NEWS_FILE).exists():
        with open(SENT_NEWS_FILE, "r") as f:
            return json.load(f)
    return []

def save_sent_news(sent_news):
    with open(SENT_NEWS_FILE, "w") as f:
        json.dump(sent_news, f, indent=2)

# --- Función para enviar embed a Discord ---
def send_to_discord(title, link, summary=""):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️  No has configurado el webhook de Discord")
        return False

    payload = {
        "content": "⚠️¡¡@Miembro del Gremio hay nueva noticia de SWGOH!!⚠️",
        "embeds": [{
            "title": title,
            "url": link,
            "description": summary[:2000] if summary else "Nueva noticia de SWGOH",
            "color": 3447003,
            "footer": {"text": "SWGOH - Game Info Hub"},
            "timestamp": datetime.utcnow().isoformat()
        }]
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code in (200, 204):
            print(f"✅ Enviado a Discord: {title}")
            return True
        else:
            print(f"❌ Error al enviar a Discord: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

# --- Función principal: revisar foro y enviar novedades ---
def fetch_and_send_news():
    sent_news = load_sent_news()
    new_items_found = False

    print(f"\n🔍 Revisando foro: {FORUM_URL}")

    try:
        html = requests.get(FORUM_URL).text
        soup = BeautifulSoup(html, "html.parser")

        # Buscar los links de los posts en el blog
        posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]

        if not posts:
            print("⚠️ No se encontraron posts. Tal vez cambió la web.")
            return False

        for post in posts:
            title = post.text.strip()
            href = post.get("href")

            if not href:
                print(f"⚠️ Post sin link encontrado: {title}, se saltará")
                continue

            link = f"https://forums.ea.com{href}"
            post_id = href

            if post_id not in sent_news:
                if send_to_discord(title, link, summary=""):
                    sent_news.append(post_id)
                    new_items_found = True
                    time.sleep(1)
            else:
                print(f"⏭️  Ya enviado: {title}")

        if len(sent_news) > 100:
            sent_news = sent_news[-100:]

    except Exception as e:
        print(f"❌ Error al procesar el foro: {e}")

    if new_items_found:
        save_sent_news(sent_news)
        print("💾 Registro de noticias actualizado")

    return new_items_found


# --- Bucle principal ---
def main():
    print("🤖 Bot de noticias SWGOH iniciado")
    print(f"⏰ Revisando cada {CHECK_INTERVAL} segundos")

    if not DISCORD_WEBHOOK_URL:
        print("\n⚠️  ADVERTENCIA: No has configurado DISCORD_WEBHOOK_URL\n")

    while True:
        try:
            print(f"\n{'='*50}")
            print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            fetch_and_send_news()
            print(f"\n⏳ Esperando {CHECK_INTERVAL} segundos...")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("\n👋 Bot detenido por el usuario")
            break
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
            print(f"⏳ Reintentando en {CHECK_INTERVAL} segundos...")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
