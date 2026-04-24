import json
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from weekly_digest import configurar_scheduler, enviar_digest

NOTICIAS_FILE = "noticias.json"

def cargar_noticias():
    if not os.path.exists(NOTICIAS_FILE):
        return []
    with open(NOTICIAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_noticias(noticias):
    with open(NOTICIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def inicio_de_semana():
    hoy = datetime.now()
    lunes = hoy - timedelta(days=hoy.weekday())
    return lunes.replace(hour=0, minute=0, second=0, microsecond=0)

def noticias_esta_semana(noticias):
    desde = inicio_de_semana()
    return [n for n in noticias if datetime.fromisoformat(n["fecha"]) >= desde]

async def guardar_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    noticias = cargar_noticias()
    noticias.append({"texto": texto, "fecha": datetime.now().isoformat()})
    guardar_noticias(noticias)
    total = len(noticias_esta_semana(noticias))
    await update.message.reply_text(f"✅ Guardado. Ya tengo {total} noticias esta semana.")

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    noticias = noticias_esta_semana(cargar_noticias())
    if not noticias:
        await update.message.reply_text("No hay noticias guardadas esta semana.")
        return
    lineas = [f"{i}. [{datetime.fromisoformat(n['fecha']).strftime('%d/%m %H:%M')}] {n['texto']}" for i, n in enumerate(noticias, 1)]
    await update.message.reply_text("🔍 Debug: versión actual cargada correctamente\n\n📋 *Noticias de esta semana:*\n\n" + "\n\n".join(lineas), parse_mode="Markdown")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guardar_noticias([])
    await update.message.reply_text("🗑️ Lista limpiada. Nueva semana.")

async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Procesando digest...")
    try:
        await enviar_digest(context.application)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def on_startup(app):
    scheduler = configurar_scheduler(app)
    scheduler.start()

def main():
    token = os.environ["TELEGRAM_TOKEN"]
    app = ApplicationBuilder().token(token).post_init(on_startup).build()
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("limpiar", limpiar))
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_noticia))
    print("Bot v2 iniciado.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
