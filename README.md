# SWGOH News Bot

Este es un bot de Discord que envía automáticamente las últimas noticias del foro **Star Wars: Galaxy of Heroes** al canal de Discord configurado mediante un webhook.

---

## Características

- Obtiene los posts más recientes del foro oficial de SWGOH.  
- Envía un **embed** con título y enlace a Discord.  
- Evita duplicados usando un archivo `sent_news.json`.  
- Opcional: envía notificaciones a `@everyone` en Discord.  
- Funciona 24/7 en plataformas como **Render Free**.

---

## Archivos importantes

- `main.py` → código principal del bot.  
- `sent_news.json` → registro de noticias enviadas.  
- `requirements.txt` → dependencias de Python necesarias.  

---

## Dependencias

Instalar las librerías necesarias:

```bash
pip install -r requirements.txt
