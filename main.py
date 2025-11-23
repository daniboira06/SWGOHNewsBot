import requests
from bs4 import BeautifulSoup
import time
import os
from datetime import datetime, timezone
from flask import Flask
import threading
import sqlite3
from pathlib import Path

app = Flask(__name__)

@app.route("/")
def home():
    return "SWGOH Bot activo 😎"

def run_web():
    # Desactivar logs de Flask para que no ensucien la consola
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=5000)

# --- CONFIGURACIÓN ---
FORUM_URL = "https://forums.ea.com/category/star-wars-galaxy-of-heroes-en/blog/swgoh-game-info-hub-en"
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')
CHECK_INTERVAL = 300

# Usar /data si existe (Render Disk), sino usar directorio local
DB_DIR = "/data" if os.path.exists("/data") else "."
DB_PATH = os.path.join(DB_DIR, "swgoh_news.db")

print(f"📁 Usando base de datos en: {DB_PATH}")

# --- Funciones de base de datos SQLite ---
def init_database():
    """Inicializa la base de datos SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Crear tabla si no existe
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
        
        print(f"✅ Base de datos inicializada correctamente")
        return True
    except Exception as e:
        print(f"❌ Error al inicializar base de datos: {e}")
        return False

def is_post_sent(post_id):
    """Verifica si un post ya fue enviado"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sent_news WHERE post_id = ?", (post_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"❌ Error al verificar post: {e}")
        return False

def mark_post_as_sent(post_id, title, link):
    """Marca un post como enviado"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sent_news (post_id, title, link) VALUES (?, ?, ?)",
            (post_id, title, link)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error al guardar post: {e}")
        return False

def cleanup_old_posts():
    """Limpia posts antiguos (mantiene solo los últimos 100)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Contar posts
        cursor.execute("SELECT COUNT(*) FROM sent_news")
        count = cursor.fetchone()[0]
        
        if count > 100:
            # Eliminar los más antiguos
            cursor.execute('''
                DELETE FROM sent_news 
                WHERE post_id NOT IN (
                    SELECT post_id FROM sent_news 
                    ORDER BY sent_at DESC 
                    LIMIT 100
                )
            ''')
            deleted = cursor.rowcount
            conn.commit()
            print(f"🧹 Limpieza: eliminados {deleted} posts antiguos")
        
        conn.close()
    except Exception as e:
        print(f"❌ Error en limpieza: {e}")

def get_post_count():
    """Obtiene el número de posts guardados"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sent_news")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

# --- Inicialización: marcar noticias actuales como leídas ---
def initialize_existing_news():
    """Marca las noticias actuales del foro como ya leídas sin enviarlas"""
    count = get_post_count()
    
    if count > 0:
        print(f"📊 Base de datos ya tiene {count} noticias registradas")
        return
    
    print("🔄 Primera ejecución: marcando noticias actuales como leídas...")
    
    try:
        response = requests.get(FORUM_URL, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f"❌ Error al obtener la página: {e}")
        return
    
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.select("h4 a[href*='/blog/swgoh-game-info-hub-en/']")[:5]
    
    for post in posts:
        title = post.text.strip()
        href = post.get("href")
        
        if not href:
            continue
        
        link = f"https://forums.ea.com{href}"
        post_id = href
        
        mark_post_as_sent(post_id, title, link)
        print(f"  ✓ Marcada: {title}")
    
    print(f"✅ {len(posts)} noticias marcadas como leídas (no enviadas)\n")

# --- Envío a Discord ---
def send_to_discord(title, link, summary=""):
    """Envía notificación a Discord"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No has configurado el webhook de Discord")
        return False

    payload = {
        "content": "⚠️ ¡¡<@745741680430546954> hay nueva noticia de SWGOH!! ⚠️",
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
    """Revisa el foro y envía noticias nuevas"""
    print(f"\n🔍 Revisando foro: {FORUM_URL}")

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

        # Verificar si ya fue enviado
        if is_post_sent(post_id):
            print(f"⏭️ Ya enviado anteriormente: {title}")
            continue

        # Nuevo post encontrado
        print(f"🆕 Nueva noticia detectada: {title}")
        
        if send_to_discord(title, link, summary=""):
            if mark_post_as_sent(post_id, title, link):
                print("💾 Post guardado en base de datos")
                new_items_found = True
                time.sleep(1)  # Pausa entre envíos

    if new_items_found:
        cleanup_old_posts()

    return new_items_found

# --- Bucle principal ---
def bot_loop():
    """Bucle que revisa las noticias continuamente"""
    print("🤖 Bot de noticias SWGOH iniciado")
    print(f"⏰ Revisando cada {CHECK_INTERVAL} segundos")
    
    # Inicializar base de datos
    db_ok = init_database()
    
    if db_ok:
        # Si es la primera vez, marcar noticias actuales como leídas
        initialize_existing_news()
    else:
        print("⚠️ No se pudo inicializar la base de datos")
    
    print("\n" + "="*50 + "\n")

    while True:
        try:
            print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            fetch_and_send_news()
        except Exception as e:
            print(f"❌ Error en el ciclo principal: {e}")
            import traceback
            traceback.print_exc()

        print(f"⏳ Esperando {CHECK_INTERVAL} segundos...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Iniciar Flask en un thread separado
    threading.Thread(target=run_web, daemon=True).start()
    print("🌐 Servidor Flask iniciado en puerto 5000")
    
    # Ejecutar el bot en el thread principal
    bot_loop()
