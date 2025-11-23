import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from flask import Flask
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
import threading
import time
import sys

# --- CONFIGURACIÓN ---
FORUM_URL = "https://forums.ea.com/category/star-wars-galaxy-of-heroes-en/blog/swgoh-game-info-hub-en"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
CHECK_INTERVAL = 300  # 5 minutos

# Parsear DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    result = urlparse(DATABASE_URL)
    PG_HOST = result.hostname
    PG_PORT = result.port or 5432
    PG_DB = result.path.lstrip('/')
    PG_USER = result.username
    PG_PASSWORD = result.password
else:
    print("❌ DATABASE_URL no configurada")
    sys.exit(1)

# --- Flask ---
app = Flask(__name__)

@app.route("/")
def home():
    return "SWGOH Bot activo 😎"

def run_web():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=5000)

# --- Base de datos ---
def get_connection():
    """Obtiene una conexión a la base de datos con retry"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return psycopg2.connect(
                host=PG_HOST,
                port=PG_PORT,
                dbname=PG_DB,
                user=PG_USER,
                password=PG_PASSWORD,
                cursor_factory=RealDictCursor,
                connect_timeout=10
            )
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⚠️ Intento {attempt + 1} falló, reintentando... ({e})")
                time.sleep(2)
            else:
                raise

def init_database():
    """Inicializa la base de datos"""
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
        cursor.close()
        conn.close()
        print("✅ Base de datos PostgreSQL inicializada correctamente", flush=True)
        return True
    except Exception as e:
        print(f"❌ Error al inicializar base de datos: {e}", flush=True)
        return False

def is_post_sent(post_id):
    """Verifica si un post ya fue enviado"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sent_news WHERE post_id=%s", (post_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"❌ Error al verificar post: {e}", flush=True)
        return False

def mark_post_as_sent(post_id, title, link):
    """Marca un post como enviado"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sent_news (post_id, title, link) VALUES (%s, %s, %s) ON CONFLICT (post_id) DO NOTHING",
            (post_id, title, link)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error al guardar post: {e}", flush=True)
        return False

def get_post_count():
    """Obtiene el número de posts guardados"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM sent_news")
        count = cursor.fetchone()['count']
        cursor.close()
        conn.close()
        return count
    except Exception as e:
        print(f"❌ Error al contar posts: {e}", flush=True)
        return 0

def cleanup_old_posts(limit=100):
    """Limpia posts antiguos"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        count = get_post_count()
        
        if count > limit:
            cursor.execute('''
                DELETE FROM sent_news
                WHERE post_id NOT IN (
                    SELECT post_id FROM sent_news 
                    ORDER BY sent_at DESC 
                    LIMIT %s
                )
            ''', (limit,))
            deleted = cursor.rowcount
            conn.commit()
            print(f"🧹 Limpieza: eliminados {deleted} posts antiguos", flush=True)
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Error en limpieza: {e}", flush=True)

# --- Inicialización ---
def initialize_existing_news():
    """Marca las noticias actuales como leídas en el primer arranque"""
    count = get_post_count()
    
    if count > 0:
        print(f"📊 Base de datos ya tiene {count} noticias registradas", flush=True)
        return
    
    print("🔄 Primera ejecución: marcando noticias actuales como leídas...", flush=True)
    
    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]
        
        for post in posts:
            title = post.text.strip()
            href = post.get("href")
            if not href:
                continue
            link = f"https://forums.ea.com{href}"
            mark_post_as_sent(href, title, link)
            print(f"  ✓ Marcada: {title}", flush=True)
        
        print(f"✅ {len(posts)} noticias marcadas como leídas (no enviadas)\n", flush=True)
    except Exception as e:
        print(f"❌ Error inicializando noticias: {e}", flush=True)

# --- Envío a Discord ---
def send_to_discord(title, link, summary=""):
    """Envía notificación a Discord"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No has configurado el webhook de Discord", flush=True)
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
            print(f"✅ Enviado a Discord: {title}", flush=True)
            return True
        else:
            print(f"❌ Error al enviar a Discord: {response.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"❌ Error al enviar a Discord: {e}", flush=True)
        return False

# --- Revisión del foro ---
def fetch_and_send_news():
    """Revisa el foro y envía noticias nuevas"""
    print(f"\n🔍 Revisando foro: {FORUM_URL}", flush=True)
    
    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"❌ Error al obtener la página: {e}", flush=True)
        return False

    posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]

    if not posts:
        print("⚠️ No se encontraron posts. Tal vez cambió la web.", flush=True)
        return False

    new_items_found = False

    for post in posts:
        title = post.text.strip()
        href = post.get("href")

        if not href:
            print(f"⚠️ Post sin link: {title}", flush=True)
            continue

        link = f"https://forums.ea.com{href}"
        post_id = href

        if is_post_sent(post_id):
            print(f"⏭️ Ya enviado: {title}", flush=True)
            continue

        print(f"🆕 Nueva noticia: {title}", flush=True)
        
        if send_to_discord(title, link):
            if mark_post_as_sent(post_id, title, link):
                print("💾 Guardado en BD", flush=True)
                new_items_found = True
                time.sleep(2)  # Pausa entre envíos

    if new_items_found:
        cleanup_old_posts()

    return new_items_found

# --- Bucle principal ---
def bot_loop():
    """Bucle infinito que revisa noticias"""
    print("🤖 Bot de noticias SWGOH iniciado", flush=True)
    print(f"⏰ Revisando cada {CHECK_INTERVAL} segundos\n", flush=True)
    
    # Inicializar base de datos
    if not init_database():
        print("❌ No se pudo inicializar la BD. Abortando.", flush=True)
        return
    
    # Marcar noticias existentes en primer arranque
    initialize_existing_news()
    
    print("="*50 + "\n", flush=True)
    
    # Bucle infinito con manejo robusto de errores
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            fetch_and_send_news()
            consecutive_errors = 0  # Reset contador de errores
            
        except KeyboardInterrupt:
            print("\n⚠️ Bot detenido por el usuario", flush=True)
            break
            
        except Exception as e:
            consecutive_errors += 1
            print(f"❌ Error en ciclo principal ({consecutive_errors}/{max_consecutive_errors}): {e}", flush=True)
            
            if consecutive_errors >= max_consecutive_errors:
                print("❌ Demasiados errores consecutivos. Esperando 60s antes de reintentar...", flush=True)
                time.sleep(60)
                consecutive_errors = 0
        
        print(f"⏳ Esperando {CHECK_INTERVAL} segundos...\n", flush=True)
        time.sleep(CHECK_INTERVAL)

# --- Main ---
if __name__ == "__main__":
    # Iniciar Flask en thread separado
    flask_thread = threading.Thread(target=run_web, daemon=True)
    flask_thread.start()
    print("🌐 Servidor Flask iniciado en puerto 5000", flush=True)
    
    # Pequeña pausa para que Flask arranque
    time.sleep(2)
    
    # Ejecutar bot en thread principal
    bot_loop()
