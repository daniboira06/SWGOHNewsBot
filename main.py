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
CHECK_INTERVAL = 300

SENT_NEWS_FILE = "sent_news.json"
LAST_ID_FILE = "last_id.txt"

# --- Persistencia: leer último ID ---
def load_last_id():
    try:
        with open(LAST_ID_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def save_last_id(post_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(post_id)

# --- Lista de noticias enviadas ---
def load_sent_news():
    if Path(SENT_NEWS_FILE).exists():
        with open(SENT_NEWS_FILE, "r") as f:
            return json.load(f)
    return []

def save_sent_news(sent_news):
    with open(SENT_NEWS_FILE, "w") as f:
        json.dump(sent_news, f, indent=2)

# --- Envío a Discord ---
def send_to_discord(title, link, summary=""):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No has configurado el webhook de Discord")
        return False

    payload = {
        "content": "⚠️ ¡¡<@&745741680430546954> hay nueva noticia de SWGOH!! ⚠️",
        "embeds": [{
            "title": title,
            "url": link,
            "description": summary[:2000] if summary else "Nueva noticia de SWGOH",
            "color": 3447003,
            "footer": {"text": "SWGOH - Game Info Hub"},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }]
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code in (200, 204):
            print(f"✅ Enviado a Discord: {title}")
            return True
        else:
            print(f"❌ Error al enviar a Discord: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error al enviar a Discord: {e}")
        return False


# --- Revisión del foro ---
def fetch_and_send_news():
    print(f"\n🔍 Revisando foro: {FORUM_URL}")

    sent_news = load_sent_news()
    last_id = load_last_id()

    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f"❌ Error al obtener la página: {e}")
        return False

    soup = BeautifulSoup(html, "html.parser")
    posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]

    if not posts:
        print("⚠️ No se encontraron posts. Tal vez cambió la web.")
        return False

    new_items_found = False

    for post in posts:
        title = post.text.strip()
        href = post.get("href")

        if not href:
            print(f"⚠️ Post sin link encontrado: {title}, ignorado.")
            continue

        link = f"https://forums.ea.com{href}"
        post_id = href

        # Evita duplicados robustamente
        if post_id == last_id:
            print(f"⏭️ Ya enviado anteriormente (last_id): {title}")
            continue

        if post_id in sent_news:
            print(f"⏭️ Ya enviado (sent_news): {title}")
            continue

        # Nuevo post
        if send_to_discord(title, link, summary=""):
            print("💾 Guardando post enviado…")
            save_last_id(post_id)
            sent_news.append(post_id)
            new_items_found = True
            time.sleep(1)

    if new_items_found:
        save_sent_news(sent_news[-100:])  # evita archivo gigante

    return new_items_found


# --- Bucle principal protegido ---
def main():
    print("🤖 Bot de noticias SWGOH iniciado")
    print(f"⏰ Revisando cada {CHECK_INTERVAL} segundos\n")

    while True:
        try:
            print("\n" + "="*50)
            print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            fetch_and_send_news()
        except Exception as e:
            print(f"❌ Error en el ciclo principal: {e}")

        print(f"⏳ Esperando {CHECK_INTERVAL} segundos...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

