import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from flask import Flask
import psycopg2
from psycopg2.extras import RealDictCursor
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURACIÓN ---
FORUM_URL = "https://forums.ea.com/category/star-wars-galaxy-of-heroes-en/blog/swgoh-game-info-hub-en"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Variables de entorno para Postgres
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_DB = os.getenv("PG_DB", "swgoh")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

# --- Flask ---
app = Flask(__name__)

@app.route("/")
def home():
    return "SWGOH Bot activo 😎"

# --- Base de datos ---
def get_connection():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        cursor_factory=RealDictCursor
    )

def init_database():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_news (
                post_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        print("✅ Base de datos inicializada correctamente")
        return True
    except Exception as e:
        print(f"❌ Error al inicializar base de datos: {e}")
        return False

def is_post_sent(post_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sent_news WHERE post_id=%s", (post_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"❌ Error al verificar post: {e}")
        return False

def mark_post_as_sent(post_id, title, link):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sent_news (post_id, title, link) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (post_id, title, link)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error al guardar post: {e}")
        return False

def cleanup_old_posts(limit=100):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sent_news")
        count = cursor.fetchone()['count']
        if count > limit:
            cursor.execute('''
                DELETE FROM sent_news
                WHERE post_id NOT IN (
                    SELECT post_id FROM sent_news ORDER BY sent_at DESC LIMIT %s
                )
            ''', (limit,))
            deleted = cursor.rowcount
            conn.commit()
            print(f"🧹 Limpieza: eliminados {deleted} posts antiguos")
        conn.close()
    except Exception as e:
        print(f"❌ Error en limpieza: {e}")

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
            "timestamp": datetime.now(timezone.utc).isoformat()
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
    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f"❌ Error al obtener la página: {e}")
        return False

    from bs4 import BeautifulSoup
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
            continue
        link = f"https://forums.ea.com{href}"
        post_id = href
        if is_post_sent(post_id):
            print(f"⏭️ Ya enviado anteriormente: {title}")
            continue

        print(f"🆕 Nueva noticia detectada: {title}")
        if send_to_discord(title, link):
            if mark_post_as_sent(post_id, title, link):
                print("💾 Post guardado en base de datos")
                new_items_found = True

    if new_items_found:
        cleanup_old_posts()
    return new_items_found

# --- Inicialización ---
def initialize_existing_news():
    print("🔄 Marcando noticias actuales como leídas (si es la primera ejecución)...")
    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]
        for post in posts:
            title = post.text.strip()
            href = post.get("href")
            if not href:
                continue
            link = f"https://forums.ea.com{href}"
            mark_post_as_sent(href, title, link)
        print(f"✅ {len(posts)} noticias marcadas como leídas")
    except Exception as e:
        print(f"❌ Error inicializando noticias existentes: {e}")

# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_and_send_news, 'interval', minutes=5)
scheduler.start()

# --- Main ---
if __name__ == "__main__":
    if init_database():
        initialize_existing_news()
    else:
        print("⚠️ No se pudo inicializar la base de datos")

    print("🌐 Iniciando servidor Flask en puerto 5000")
    app.run(host="0.0.0.0", port=5000)

