import json
import os
import re
from datetime import datetime, timedelta
import httpx
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from weekly_digest import configurar_scheduler, enviar_digest

from generator import run as run_generator

NOTICIAS_FILE = "noticias.json"
URL_RE = re.compile(r'https?://\S+')

PROMPT_NOTICIA = (
    "Eres un editor de newsletter especializado en startups e inversión. "
    "Convierte la noticia en un resumen breve, preciso y publicable.\n\n"
    "Escribe un único párrafo de 3-4 líneas. "
    "Estructura: sujeto + acción principal + cifra o condición clave + finalidad. "
    "Negritas para nombre de empresa, cifras e inversores. Cifras: 450k, 20M€. "
    "Cierra con el medio enlazado: [[Nombre del medio]](url). "
    "Tono periodístico, directo. No inventes nada."
)

PROMPT_AGENDA = (
    "Extrae la información de este evento y devuelve SOLO esto, en una línea:\n"
    "**[Nombre del evento]**. [Fecha/s]. [Ciudad]. [Una línea de descripción]. [[Más info]](URL)\n\n"
    "Sustituye URL por el enlace real. Si no encuentras algún dato, omítelo. No inventes nada."
)

PROMPT_CONVOCATORIA = (
    "Extrae la información de esta convocatoria y devuelve SOLO esto, en una línea:\n"
    "**[Nombre de la convocatoria]**. Cierra: [Fecha límite]. [Para quién es y qué ofrece, una línea]. [[Más info]](URL)\n\n"
    "Sustituye URL por el enlace real. Si no encuentras algún dato, omítelo. No inventes nada."
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


def _contar_por_tipo(noticias, tipo):
    return len([n for n in noticias_esta_semana(noticias) if n.get("tipo", "noticia") == tipo])


async def _claude(contenido: str, system: str) -> str:
    ai = anthropic.AsyncAnthropic()
    msg = await ai.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": contenido}],
    )
    return msg.content[0].text


async def _fetch(url: str) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text[:15000]


async def _guardar_entrada(update, texto: str, tipo: str, confirmacion: str):
    noticias = cargar_noticias()
    noticias.append({"texto": texto, "fecha": datetime.now().isoformat(), "tipo": tipo})
    guardar_noticias(noticias)
    total = _contar_por_tipo(noticias, tipo)
    await update.message.reply_text(f"{confirmacion} ({total} esta semana)\n\n{texto}")


# ── /noticia ──────────────────────────────────────────────────────────────────

async def cmd_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args_text = " ".join(context.args).strip() if context.args else ""
    if not args_text:
        await update.message.reply_text(
            "Uso:\n"
            "`/noticia https://link.com` — intento leerlo y resumirlo\n"
            "`/noticia texto de la noticia` — lo proceso directamente",
            parse_mode="Markdown"
        )
        return

    match = URL_RE.search(args_text)

    if match:
        url = match.group()
        texto_extra = args_text.replace(url, "").strip()

        if texto_extra:
            contenido = texto_extra
        else:
            try:
                contenido = await _fetch(url)
            except Exception:
                # No puede acceder: guarda el link y pide texto
                noticias = cargar_noticias()
                noticias.append({"texto": url, "url": url, "fecha": datetime.now().isoformat(), "tipo": "noticia"})
                guardar_noticias(noticias)
                await update.message.reply_text(
                    f"🔗 No pude acceder al medio. Guardé el link.\n"
                    f"Si tienes el texto, mándamelo así:\n`/noticia [pega aquí el texto]`",
                    parse_mode="Markdown"
                )
                return

        try:
            texto_final = await _claude(f"{contenido}\n\nFuente: {url}", PROMPT_NOTICIA)
        except Exception as e:
            texto_final = args_text
            await update.message.reply_text(f"⚠️ Claude falló, guardé el texto sin procesar. Error: {e}")

        await _guardar_entrada(update, texto_final, "noticia", "✅ Noticia guardada.")
    else:
        # Solo texto sin URL
        try:
            texto_final = await _claude(args_text, PROMPT_NOTICIA)
        except Exception:
            texto_final = args_text
        await _guardar_entrada(update, texto_final, "noticia", "✅ Noticia guardada.")


# ── /agenda ───────────────────────────────────────────────────────────────────

async def cmd_agenda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args_text = " ".join(context.args).strip() if context.args else ""
    if not args_text:
        await update.message.reply_text(
            "Uso:\n"
            "`/agenda https://link.com` — extraigo los datos del evento\n"
            "`/agenda Nombre. Fecha. Ciudad. Descripción.` — lo formato directamente",
            parse_mode="Markdown"
        )
        return

    match = URL_RE.search(args_text)

    if match:
        url = match.group()
        texto_extra = args_text.replace(url, "").strip()
        contenido = texto_extra if texto_extra else None

        if not contenido:
            try:
                contenido = await _fetch(url)
            except Exception:
                await update.message.reply_text(
                    "🔗 No pude acceder al link. Mándame los datos así:\n"
                    "`/agenda Nombre evento. Fechas. Ciudad. Descripción breve.`",
                    parse_mode="Markdown"
                )
                return

        try:
            texto_final = await _claude(f"{contenido}\n\nURL: {url}", PROMPT_AGENDA)
        except Exception:
            texto_final = args_text
    else:
        try:
            texto_final = await _claude(args_text, PROMPT_AGENDA)
        except Exception:
            texto_final = args_text

    await _guardar_entrada(update, texto_final, "agenda", "📅 Evento guardado.")


# ── /convocatoria ─────────────────────────────────────────────────────────────

async def cmd_convocatoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args_text = " ".join(context.args).strip() if context.args else ""
    if not args_text:
        await update.message.reply_text(
            "Uso:\n"
            "`/convocatoria https://link.com` — extraigo los datos\n"
            "`/convocatoria Nombre. Fecha límite. Descripción.` — lo formato directamente",
            parse_mode="Markdown"
        )
        return

    match = URL_RE.search(args_text)

    if match:
        url = match.group()
        texto_extra = args_text.replace(url, "").strip()
        contenido = texto_extra if texto_extra else None

        if not contenido:
            try:
                contenido = await _fetch(url)
            except Exception:
                await update.message.reply_text(
                    "🔗 No pude acceder al link. Mándame los datos así:\n"
                    "`/convocatoria Nombre. Fecha límite. Para quién. Qué ofrece.`",
                    parse_mode="Markdown"
                )
                return

        try:
            texto_final = await _claude(f"{contenido}\n\nURL: {url}", PROMPT_CONVOCATORIA)
        except Exception:
            texto_final = args_text
    else:
        try:
            texto_final = await _claude(args_text, PROMPT_CONVOCATORIA)
        except Exception:
            texto_final = args_text

    await _guardar_entrada(update, texto_final, "convocatoria", "🎯 Convocatoria guardada.")


# ── Otros comandos ────────────────────────────────────────────────────────────

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    todas = noticias_esta_semana(cargar_noticias())
    if not todas:
        await update.message.reply_text("No hay nada guardado esta semana.")
        return

    secciones = []
    for tipo, emoji, label in [
        ("noticia", "📰", "NOTICIAS"),
        ("agenda", "📅", "AGENDA"),
        ("convocatoria", "🎯", "CONVOCATORIAS"),
    ]:
        items = [n for n in todas if n.get("tipo", "noticia") == tipo]
        if items:
            lineas = [
                f"{i}. [{datetime.fromisoformat(n['fecha']).strftime('%d/%m %H:%M')}] {n['texto'][:120]}"
                for i, n in enumerate(items, 1)
            ]
            secciones.append(f"{emoji} *{label}* ({len(items)})\n" + "\n".join(lineas))

    await update.message.reply_text("\n\n".join(secciones), parse_mode="Markdown")


async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guardar_noticias([])
    await update.message.reply_text("🗑️ Lista limpiada. Nueva semana.")


async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Procesando digest...")
    try:
        await enviar_digest(context.application)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def generar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generando contenido... Esto puede tardar un minuto.")
    try:
        await run_generator()
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def on_startup(app):
    scheduler = configurar_scheduler(app)
    scheduler.start()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ["TELEGRAM_TOKEN"]
    app = ApplicationBuilder().token(token).post_init(on_startup).build()

    app.add_handler(CommandHandler("noticia", cmd_noticia))
    app.add_handler(CommandHandler("agenda", cmd_agenda))
    app.add_handler(CommandHandler("convocatoria", cmd_convocatoria))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("limpiar", limpiar))
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(CommandHandler("generar", generar))

    print("Bot v3 iniciado.")

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
