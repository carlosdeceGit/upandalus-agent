import json
import os
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from generator import run as generar

NOTICIAS_FILE = "noticias.json"
MADRID_TZ = pytz.timezone("Europe/Madrid")


def cargar_noticias():
    if not os.path.exists(NOTICIAS_FILE):
        return []
    with open(NOTICIAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_noticias(noticias):
    with open(NOTICIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)


def construir_mensaje(noticias):
    if not noticias:
        return "📋 No hay noticias guardadas esta semana."

    fechas = [datetime.fromisoformat(n["fecha"]) for n in noticias]
    fecha_min = min(fechas).strftime("%d/%m/%Y")
    fecha_max = max(fechas).strftime("%d/%m/%Y")
    total = len(noticias)

    resumenes = "\n".join(n["texto"] for n in noticias)

    return (
        f"📋 NOTICIAS GUARDADAS ESTA SEMANA\n"
        f"Del {fecha_min} al {fecha_max}\n"
        f"Total: {total} noticias\n"
        f"---\n"
        f"{resumenes}\n"
        f"---\n"
        f"✅ Copia esto y pégalo en Cowork junto con la tarea de curación de Gmail."
    )


async def enviar_digest(app):
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    try:
        noticias = cargar_noticias()
        mensaje = construir_mensaje(noticias)
        await app.bot.send_message(chat_id=chat_id, text=mensaje)
        if noticias:
            guardar_noticias([])
    except Exception as e:
        await app.bot.send_message(chat_id=chat_id, text=f"❌ Error en digest: {e}")


def configurar_scheduler(app):
    scheduler = AsyncIOScheduler(timezone=MADRID_TZ)
    scheduler.add_job(
        enviar_digest,
        trigger="cron",
        day_of_week="sun",
        hour=11,
        minute=0,
        args=[app],
    )
    scheduler.add_job(
        generar,
        trigger="cron",
        day_of_week="sun",
        hour=11,
        minute=0,
        id="generar_contenido_semanal",
    )
    return scheduler
