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
    resultado = []
    for n in noticias:
        fecha = datetime.fromisoformat(n["fecha"])
        if fecha >= desde:
            resultado.append(n)
    return resultado


async def guardar_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    noticias = cargar_noticias()

    nueva = {
        "texto": texto,
        "fecha": datetime.now().isoformat()
    }
    noticias.append(nueva)
    guardar_noticias(noticias)

    total_semana = len(noticias_esta_semana(noticias))
    await update.message.reply_text(
        f"✅ Guardado. Ya tengo {total_semana} noticias esta semana."
    )


async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Debug: versión actual cargada correctamente")
    noticias = cargar_noticias()
    semana = noticias_esta_semana(noticias)

    if not semana:
        await update.message.reply_text("No hay noticias guardadas esta semana.")
        return

    lineas = []
    for i, n in enumerate(semana, 1):
        fecha = datetime.fromisoformat(n["fecha"]).strftime("%d/%m %H:%M")
        lineas.append(f"{i}. [{fecha}] {n['texto']}")

    mensaje = "📋 *Noticias de esta semana:*\n\n" + "\n\n".join(lineas)
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guardar_noticias([])
    await update.message.reply_text("🗑️ Lista limpiada. Nueva semana, nueva lista.")


async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Procesando digest...")
    try:
        await enviar_digest(context.application)
    except Exception as e:
        await update.message.reply_text(f"❌ Error llamando a enviar_digest: {e}")


async def on_startup(app):
    scheduler = configurar_scheduler(app)
    scheduler.start()


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).post_init(on_startup).build()

    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("limpiar", limpiar))
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_noticia))

    print("BOT VERSION 2 - handlers: resumen, limpiar, digest, guardar")
    print("Bot iniciado.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
