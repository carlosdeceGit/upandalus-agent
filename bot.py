import json
import os
import re
from datetime import datetime, timedelta
import httpx
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from weekly_digest import configurar_scheduler, enviar_digest

NOTICIAS_FILE = "noticias.json"
URL_RE = re.compile(r'https?://\S+')
SYSTEM_PROMPT = (
    "Eres un editor de newsletter especializado en startups e inversión. Tu única tarea es convertir noticias en resúmenes breves, precisos y publicables para la newsletter UpAndalus.\n"
    "Reglas fijas:\n\n"
    "Resume SOLO el contenido que te llega. No añadas contexto externo.\n"
    "Detecta el tipo de noticia y extrae lo nuclear: inversión (empresa + cantidad + inversores + uso del dinero), ayuda pública (importe + objetivo + destinatarios + plazos), corporativa (qué hace la empresa + movimiento relevante)\n"
    "Escribe un único párrafo de 3-4 líneas. Máxima densidad informativa.\n"
    "Estructura: sujeto + acción principal + cifra o condición clave + finalidad o consecuencia\n"
    "Usa negritas para resaltar nombre de empresa, cifras e inversores principales\n"
    "Cifras económicas siempre abreviadas: 450k, 20M€\n"
    "Cierra con el medio enlazado en este formato exacto: [Nombre del medio]\n"
    "Tono periodístico: directo, informativo, profesional. Sin adornos.\n"
    "No inventes ni interpretes más allá del texto"
)

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

async def procesar_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        contenido = resp.text[:15000]
    ai = anthropic.AsyncAnthropic()
    msg = await ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": contenido}],
    )
    return msg.content[0].text


async def guardar_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    noticias = cargar_noticias()

    match = URL_RE.search(texto)
    if match:
        url = match.group()
        try:
            texto_a_guardar = await procesar_url(url)
        except Exception:
            noticias.append({"texto": url, "fecha": datetime.now().isoformat()})
            guardar_noticias(noticias)
            await update.message.reply_text("⚠️ No pude procesar el link, guardé la URL directamente")
            return
    else:
        texto_a_guardar = texto

    noticias.append({"texto": texto_a_guardar, "fecha": datetime.now().isoformat()})
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

    port = int(os.environ.get("PORT", 8080))
    railway_url = os.environ["RAILWAY_STATIC_URL"]

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=f"https://{railway_url}/webhook",
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
