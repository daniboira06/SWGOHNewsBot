import requests
from bs4 import BeautifulSoup
import time
import os
from datetime import datetime
from flask import Flask
import threading
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

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
MONGODB_URI = os.getenv('MONGODB_URI', '')  # Nueva variable de entorno
CHECK_INTERVAL = 300

# --- Conexión a MongoDB ---
db = None
sent_collection = None

def init_database():
    """Inicializa la conexión a MongoDB"""
    global db, sent_collection
    
    if not MONGODB_URI:
        print("⚠️ MONGODB_URI no configurada. Usando modo fallback (memoria).")
        return False
    
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        # Verificar conexión
        client.admin.command('ping')
        db = client['swgoh_bot']
        sent_collection = db['sent_news']
        
        # Crear índice para búsquedas rápidas
        sent_collection.create_index("post_id", unique=True)
        
        print("✅ Conectado a MongoDB correctamente")
        return True
    except ConnectionFailure as e:
        print(f"❌ Error al conectar a MongoDB: {e}")
        return False
    except Exception as e:
        print(f"❌ Error inesperado con MongoDB: {e}")
        return False

# --- Funciones de persistencia con MongoDB ---
def is_post_sent(post_id):
    """Verifica si un post ya fue enviado"""
    if sent_collection is None:
        return False
    
    try:
        return sent_collection.find_one({"post_id": post_id}) is not None
    except Exception as e:
        print(f"❌ Error al verificar post: {e}")
        return False

def mark_post_as_sent(post_id, title, link):
    """Marca un post como enviado"""
    if sent_collection is None:
        return False
    
    try:
        sent_collection.insert_one({
            "post_id": post_id,
            "title": title,
            "link": link,
            "sent_at": datetime.utcnow()
        })
        return True
    except Exception as e:
        print(f"❌ Error al guardar post: {e}")
        return False

def cleanup_old_posts():
    """Limpia posts antiguos (mantiene solo los últimos 100)"""
    if sent_collection is None:
        return
    
    try:
        count = sent_collection.count_documents({})
        if count > 100:
            # Obtener los 100 más recientes
            recent = list(sent_collection.find().sort("sent_at", -1).limit(100))
            recent_ids = [doc["_id"] for doc in recent]
            
            # Eliminar el resto
            sent_collection.delete_many({"_id": {"$nin": recent_ids}})
            print(f"🧹 Limpieza: eliminados {count - 100} posts antiguos")
    except Exception as e:
        print(f"❌ Error en limpieza: {e}")

# --- Envío a Discord ---
def send_to_discord(title, link, summary=""):
    """Envía notificación a Discord"""
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
    db_connected = init_database()
    
    if not db_connected:
        print("⚠️ Continuando sin base de datos (solo para testing)")
    
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
