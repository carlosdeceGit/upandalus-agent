import asyncio
import json
import os
from datetime import date

import anthropic
import httpx

NOTICIAS_FILE = "noticias.json"
PUBLICADAS_FILE = "noticias_publicadas.json"
CRACKS_FILE = "cracks_transcripcion.txt"

BRAVE_QUERIES = [
    "startups España inversión ronda",
    "capital riesgo España fondos",
    "emprendimiento España ecosistema",
    "subvenciones startups España convocatoria",
    "aceleradoras incubadoras España",
    "eventos emprendimiento España",
    "startups Andalucía inversión",
    "startups Valencia Galicia Euskadi",
    "tecnología innovación empresas España",
    "exits adquisiciones startups España",
]

SYSTEM_PROMPT = """Eres el editor de UpAndalus, newsletter semanal del ecosistema emprendedor español más allá de Madrid y Barcelona. Generas el contenido completo de la semana.

IDENTIDAD EDITORIAL:
Voz directa, opinionada, con criterio. Sin hype ni adjetivos vacíos. Nunca: "innovador", "disruptivo", "revolucionario", "apasionante", "sin duda", "en un mundo donde", "en el panorama actual", "En resumen", "En definitiva". Datos concretos siempre. Cifras en k y M€. Foco en Andalucía y España fuera de Madrid/Barcelona. Madrid/Barcelona solo si supera 20M€ o es impacto nacional excepcional. Tono: alguien que conoce el ecosistema de primera mano y no tiene paciencia para el relleno.

FILTRO NOTICIAS — solo entran:
Rondas de inversión, nuevos fondos, exits/adquisiciones, productos con tracción real, subvenciones y convocatorias públicas, eventos del ecosistema, alianzas estratégicas con impacto real, regulación que afecte a startups.

FORMATO CADA NOTICIA:
Párrafo único 3-4 líneas. Estructura: sujeto + acción + cifra clave + finalidad. Negritas para nombre empresa, cifras e inversores. Cifras: 450k, 20M€. Cierre: [[Nombre medio]](url). Máx 10 noticias, mín 8. Clasificadas en: 🚀 Startups & Scaleups / 💰 Fondos - M&A / 📰 Otras.

SECCIÓN CRACKS (si hay transcripción):
Primera persona del fundador/a. Natural, como si él/ella lo escribiera. Cubre: qué hace, quiénes son, cuándo empezó y cuánto han invertido, cómo ganan dinero, próximos meses, recomendación de startup o persona, algo que anunciar.

SECCIÓN LA OPINIÓN (si hay transcripción):
250-350 palabras. Estructura: 1) mercado primero no empresa, 2) lo genuinamente interesante visto desde fuera, 3) dudas reales con datos y benchmarks, 4) cierre con una idea no un resumen. Cercano pero no colega. Directo pero no arrogante.

POST LINKEDIN:
Primera frase corta sobre el protagonista de Cracks. Párrafo sobre esa startup (2-3 líneas). Luego 4-5 noticias potentes con 🟢. Luego 4 eventos más cercanos con 🔵. Luego 4 convocatorias más cercanas con 🟣. Cierra con [INTRO CARLOS — espacio para texto personal]. Máx 3 hashtags al final.

IDEAS CARRUSEL INSTAGRAM/TIKTOK:
3 ideas basadas en las noticias más potentes. Cada idea: título + 5-7 slides con texto de cada una. Primera slide siempre con el hook más potente. Formato directo para no-lectores.

TÍTULOS NEWSLETTER:
5 opciones. Cortos, directos, que no suenen a newsletter corporativa. Basados en la noticia o el Cracks más potente.

Responde en este formato JSON exacto:
{"newsletter": "...", "linkedin": "...", "carrusel": "...", "titulos": "..."}"""


def _cargar_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _buscar_brave(client: httpx.AsyncClient, query: str, api_key: str) -> list:
    try:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key},
            params={"q": query, "freshness": "pw", "count": 10},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("web", {}).get("results", [])
    except Exception:
        return []


async def _recopilar_brave(api_key: str) -> list:
    async with httpx.AsyncClient() as client:
        grupos = await asyncio.gather(
            *[_buscar_brave(client, q, api_key) for q in BRAVE_QUERIES]
        )
    urls_vistas = set()
    noticias = []
    for grupo in grupos:
        for item in grupo:
            url = item.get("url", "")
            if url and url not in urls_vistas:
                urls_vistas.add(url)
                noticias.append({
                    "titulo": item.get("title", ""),
                    "url": url,
                    "descripcion": item.get("description", ""),
                })
    return noticias


def _deduplicar(noticias: list, publicadas: dict) -> list:
    urls_pub = set(publicadas.get("urls", []))
    titulos_pub = set(publicadas.get("titulos", []))
    return [
        n for n in noticias
        if n.get("url") not in urls_pub and n.get("titulo") not in titulos_pub
    ]


def _llamar_claude(noticias_bot: list, noticias_brave: list, cracks_texto: str) -> dict:
    secciones = []
    if noticias_bot:
        lineas = "\n".join(f"- {n['texto']}" for n in noticias_bot)
        secciones.append(f"## NOTICIAS DEL BOT\n{lineas}")
    if noticias_brave:
        lineas = "\n".join(
            f"- [{n['titulo']}]({n['url']}): {n['descripcion']}"
            for n in noticias_brave[:50]
        )
        secciones.append(f"## NOTICIAS BRAVE SEARCH\n{lineas}")
    if cracks_texto:
        secciones.append(f"## TRANSCRIPCIÓN CRACKS\n{cracks_texto}")

    user_msg = "\n\n".join(secciones) if secciones else "Sin noticias disponibles esta semana."

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    respuesta = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = respuesta.content[0].text
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except Exception as e:
        raise ValueError(f"Claude no devolvió JSON válido: {e}\n\nRespuesta:\n{raw[:500]}")


async def _enviar_telegram(token: str, chat_id: str, titulo: str, texto: str):
    MAX = 4096
    contenido = f"{titulo}\n\n{texto}"
    partes = [contenido[i:i + MAX] for i in range(0, len(contenido), MAX)]
    async with httpx.AsyncClient() as client:
        for parte in partes:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": parte},
                timeout=15,
            )


async def run():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    brave_key = os.environ.get("BRAVE_API_KEY", "")

    # Paso 1a: noticias del bot
    noticias_bot = _cargar_json(NOTICIAS_FILE, [])

    # Paso 1b: histórico de URLs publicadas
    publicadas = _cargar_json(PUBLICADAS_FILE, {"urls": [], "titulos": []})

    # Paso 1c: Brave Search en paralelo (si hay clave)
    noticias_brave = []
    if brave_key:
        noticias_brave = await _recopilar_brave(brave_key)

    # Paso 1d: transcripción Cracks
    cracks_texto = ""
    if os.path.exists(CRACKS_FILE):
        with open(CRACKS_FILE, "r", encoding="utf-8") as f:
            cracks_texto = f.read().strip()

    # Paso 1e: deduplicar contra histórico
    noticias_brave = _deduplicar(noticias_brave, publicadas)

    # Paso 2: generar con Claude
    try:
        output = _llamar_claude(noticias_bot, noticias_brave, cracks_texto)
    except Exception as e:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"❌ Error generando contenido:\n{e}"},
                timeout=15,
            )
        return

    # Paso 3a: guardar output con fecha
    _guardar_json(f"output_{date.today().isoformat()}.json", output)

    # Paso 3b: actualizar histórico de publicadas
    nuevas_urls = [n["url"] for n in noticias_brave if n.get("url")]
    nuevos_titulos = [n["titulo"] for n in noticias_brave if n.get("titulo")]
    publicadas["urls"] = list(set(publicadas.get("urls", []) + nuevas_urls))
    publicadas["titulos"] = list(set(publicadas.get("titulos", []) + nuevos_titulos))
    _guardar_json(PUBLICADAS_FILE, publicadas)

    # Paso 3c: limpiar fuentes de entrada
    _guardar_json(NOTICIAS_FILE, [])
    if os.path.exists(CRACKS_FILE):
        os.remove(CRACKS_FILE)

    # Paso 3d: enviar las 4 secciones por Telegram
    for titulo, clave in [
        ("📰 NEWSLETTER", "newsletter"),
        ("💼 LINKEDIN", "linkedin"),
        ("🎬 CARRUSEL", "carrusel"),
        ("📝 TÍTULOS", "titulos"),
    ]:
        await _enviar_telegram(token, chat_id, titulo, output.get(clave, ""))


if __name__ == "__main__":
    asyncio.run(run())
