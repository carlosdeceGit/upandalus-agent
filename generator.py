import asyncio
import json
import os
import re
from datetime import date

import anthropic
import httpx
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

NOTICIAS_FILE = "noticias.json"
PUBLICADAS_FILE = "noticias_publicadas.json"
CRACKS_FILE = "cracks_transcripcion.txt"
LOGO_PNG = "assets/logo_temp.png"

_PAGE_W, _PAGE_H = 1080, 1080
_HEADER_H = 80
_HEADER_COLOR = HexColor("#15944f")
_BODY_MARGIN = 60

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
    "eventos emprendimiento startups España próximos",
    "agenda innovación tecnología España",
    "convocatorias subvenciones startups España 2026",
    "aceleradoras incubadoras convocatoria abierta España",
    "eventos startup España",
    "premios concursos emprendimiento España 2026",
    "CDTI ENISA ayudas startups 2026",
    "Junta Andalucía subvenciones startups innovación",
    "eventos emprendimiento Andalucía Valencia Galicia Euskadi",
]

SYSTEM_PROMPT = """Eres el editor de UpAndalus, newsletter semanal del ecosistema emprendedor español más allá de Madrid y Barcelona. Tu trabajo es generar el contenido completo de cada edición.

IDENTIDAD EDITORIAL:
Tono directo, cercano, con criterio. Nunca corporativo. Carlos escribe en primera persona y opina sin filtros. La IA ayuda pero el contenido es de Carlos.
Prohibido siempre: ecosistema dinámico, proyecto apasionante, solución innovadora, innovador, disruptivo, revolucionario, sin duda, en definitiva, es un proyecto interesante, robusto, sinergias, optimizar, exclamaciones.

PRINCIPIOS DE ESCRITURA:
Activo sobre pasivo. Específico sobre vago: números, cifras, fechas concretas siempre que existan. Voz humana, no corporativa. Sin exclamaciones. Corta palabras débiles: muy, realmente, básicamente.

SWEEPS DE EDICIÓN antes de entregar cualquier sección: claridad, voz y tono, so what, prueba, especificidad.

REGLA CRÍTICA DATOS: Solo incluye noticias con fuente verificable y URL real. Nunca inventes cifras, fechas ni datos. Preferible 6 noticias verificadas que 10 con datos inventados.

FILTROS OBLIGATORIOS — aplicar antes de incluir cualquier noticia:

GEOGRAFÍA ESTRICTA:
- Solo noticias de España. Nunca Latinoamérica, nunca internacional salvo que afecte directamente al ecosistema español.
- Comunidad de Madrid y Cataluña: solo en sección 💰 Inversión & Fondos, y solo si se habla de un fondo.
- En 🚀 Startups & Scaleups: nunca Madrid ni Barcelona bajo ningún concepto.
- En 🏛️ Institucional: nunca Madrid ni Cataluña. Solo otras comunidades y convocatorias nacionales (CDTI, ENISA, ICEX).

RELEVANCIA ESTRICTA para startups y ecosistema emprendedor:
- Sí: rondas de inversión, nuevos fondos, exits, adquisiciones, productos tech con tracción, convocatorias para startups, eventos de emprendimiento e innovación.
- No: subvenciones culturales, ayudas a artistas, deportes universitarios, política, inmobiliario sin tech, grandes corporates sin relación directa con startups.
- Si tienes dudas sobre si una noticia es relevante para el ecosistema startup, descártala.

NOTICIAS DE TELEGRAM — PRIORIDAD MÁXIMA:
Las noticias en el campo noticias_telegram son noticias que Carlos ha curado manualmente durante la semana. Tienen prioridad absoluta sobre cualquier otra fuente. Todas deben aparecer en la newsletter salvo que sean un duplicado exacto. No las ignores bajo ningún concepto.

EVENTOS — criterio estricto:
Solo eventos específicamente de emprendimiento, startups, innovación o tecnología. No eventos culturales, deportivos ni generalistas. Ejemplos válidos: foros de startups, demo days, eventos de inversión, hackathons, summits de tecnología, programas de aceleración con jornada pública. Busca activamente en los resultados de búsqueda cualquier evento con estas palabras clave: startup, emprendimiento, innovación, venture, tech, demo day, summit, foro emprendedor.

FUENTES DE REFERENCIA: El Referente, El Conciso, Webcapitalriesgo, Forbes España, Valencia Plaza, Andalucía Económica, Innovaspain, Capital-Riesgo.es, Ecotechers, Expansión, Cinco Días, El Economista, Europa Press, Business Insider España, Xataka, El Español Invertia, La Información, medios regionales de todas las comunidades autónomas.

SECCIÓN 1 — NOTICIAS
Fuentes: noticias_telegram + noticias_buscadas + emails_gmail. Deduplica contra histórico.
Criterios: ronda de inversión, nuevo fondo, nuevo producto relevante, subvenciones, impacto real en ecosistema (exits, quiebras, alianzas, regulación).
Descartar: repeticiones, grandes corporates sin relación con startups, opinión sin hecho noticiable.
Formato: párrafo 2-4 líneas. Qué pasó + quién + cuánto + para qué. Negritas para empresa, cifras, inversores. Cifras: 450k, 20M€. Cierre: [[Nombre medio]](url).
Subsecciones:
🚀 Startups & Scaleups — españolas, nunca Madrid ni Barcelona salvo ronda mayor de 20M€ o impacto nacional excepcional.
💰 Inversión & Fondos — sin restricción geográfica.
🏛️ Institucional & Subvenciones — solo fuera de Madrid y Cataluña. Nacionales CDTI ENISA sí.
🛠️ Producto & Tecnología — sin restricción geográfica.
Regla: omitir subsección si no llega a 2 noticias. Total: mínimo 8, máximo 12.

SECCIÓN 2 — AGENDA DE EVENTOS
Usa noticias_buscadas y emails_gmail para encontrar eventos. Los emails son fuente prioritaria.
Eventos en los próximos 30-40 días. Solo fuera de Madrid y Barcelona.
Formato: 📅 [Fecha] — [Nombre evento], [Ciudad]. [Una línea de descripción]. [[Web](URL)]

SECCIÓN 3 — CONVOCATORIAS
Usa noticias_buscadas y emails_gmail para encontrar convocatorias. Los emails son fuente prioritaria.
Subvenciones, ayudas, incubadoras, aceleradoras, premios. Preferencia fuera de Madrid y Cataluña. Nacionales sí.
Incluir siempre: qué es y para quién + dotación + fecha límite + enlace.
Formato: descripción + [[web oficial](URL)].

SECCIÓN 4 — CRACKS
Solo si transcripcion_cracks no es null.
Redacta las respuestas del fundador manteniendo su voz. Que suene a persona real, no a nota de prensa.
Formato: pregunta en negrita, respuesta en texto normal debajo. Sin bullets.
Preguntas en orden: qué hace la startup, quiénes hay detrás, cuándo se fundó y cuánto se ha invertido, cómo ganan dinero y facturación, qué esperan en los próximos meses, recomendación de startup, algo que anunciar.
Aplica todos los sweeps de edición.

SECCIÓN 5 — LA OPINIÓN
Solo si transcripcion_cracks no es null.
Análisis de 150-300 palabras sobre la startup de Cracks.
Estructura: 1) mercado primero no empresa, 2) lo genuinamente interesante visto desde fuera, 3) dudas reales con datos o benchmarks, 4) cierre con una idea no un resumen.
Tono: cercano pero no colega. Directo pero no arrogante.
Prohibido empezar con: Sin duda, En definitiva, Es un proyecto interesante.

SECCIÓN 6 — INTRO CARLOS
Deja exactamente esto: [INTRO CARLOS — escribe aquí tu sección personal de esta semana]
No generes contenido aquí bajo ningún concepto.

POST LINKEDIN:
Primera frase corta sobre Cracks o la noticia más potente si no hay Cracks. Párrafo 2-3 líneas. Luego 4-5 noticias con 🟢. Luego 4 eventos con 🔵. Luego 4 convocatorias con 🟣. Cierra con [INTRO CARLOS]. Máximo 3 hashtags. Sin exclamaciones.

CARRUSEL INSTAGRAM/TIKTOK:
Solo usa contenido ya generado, no inventes nada nuevo.
Slide 1 — PORTADA: título impactante + Esto pasó esta semana en el ecosistema emprendedor
Slide 2 — CRACKS: nombre + qué hace + dato más relevante. Solo si hay transcripción.
Slide 3 — CRACKS continuación: reto más interesante. Solo si hay transcripción.
Slide 4 — NOTICIAS: las 3 más potentes. 🟢 + nombre + dato clave. Una línea por noticia.
Slide 5 — AGENDA: los 3 eventos más próximos. 📅 + nombre + ciudad + fecha.
Slide 6 — CONVOCATORIAS: las 3 con fecha límite más cercana. 🚀 + nombre + fecha + importe.
Slide 7 — CIERRE: Toda la info en la newsletter de UpAndalus + upandalus.substack.com
Máximo 3 líneas por slide.

TÍTULOS NEWSLETTER:
5 opciones. Cortos, directos, sin sonar a newsletter corporativa. Sin exclamaciones.

FORMATO FINAL:
Responde SOLO en JSON válido con estas claves exactas, sin texto antes ni después:
{"newsletter": "...", "linkedin": "...", "carrusel": "...", "titulos": "..."}
El campo newsletter incluye en este orden: INTRO CARLOS vacío, noticias, agenda, convocatorias, cracks, opinión.
Listo para copiar y pegar en Substack. Sin markdown raro ni bloques de código dentro del JSON."""


def _parsear_carrusel(texto: str) -> list:
    """Devuelve lista de {'titulo': str, 'slides': [str]}."""
    ideas = []
    bloques = re.split(r'\*{0,2}IDEA\s+\d+\s*[:\-]?\s*\*{0,2}', texto, flags=re.IGNORECASE)
    for bloque in bloques[1:]:
        lineas = [l.strip() for l in bloque.strip().split('\n') if l.strip()]
        if not lineas:
            continue
        titulo = lineas[0].strip('*').strip()
        slides = []
        partes = re.split(r'\*{0,2}Slide\s+\d+\s*[:\-]?\s*\*{0,2}', bloque, flags=re.IGNORECASE)
        for parte in partes[1:]:
            texto_slide = parte.strip().split('\n')[0].strip('*').strip()
            if texto_slide:
                slides.append(texto_slide)
        if slides:
            ideas.append({"titulo": titulo, "slides": slides})
    return ideas


def _wrap(text: str, font: str, size: float, max_w: float) -> list:
    words = text.split()
    lines, current = [], []
    for word in words:
        test = ' '.join(current + [word])
        if stringWidth(test, font, size) <= max_w:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines


def _dibujar_slide(c, texto: str, num: int, total: int):
    # Fondo blanco
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, _PAGE_W, _PAGE_H, fill=1, stroke=0)

    # Franja superior verde
    c.setFillColor(_HEADER_COLOR)
    c.rect(0, _PAGE_H - _HEADER_H, _PAGE_W, _HEADER_H, fill=1, stroke=0)

    # Logo (izquierda, centrado verticalmente en la franja)
    if os.path.exists(LOGO_PNG):
        logo = ImageReader(LOGO_PNG)
        lw, lh = logo.getSize()
        escala = (_HEADER_H - 20) / lh
        dw, dh = lw * escala, lh * escala
        logo_y = _PAGE_H - _HEADER_H + (_HEADER_H - dh) / 2
        c.drawImage(logo, 30, logo_y, width=dw, height=dh, mask='auto')

    # Número de slide (derecha, blanco)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 20)
    label = f"{num}/{total}"
    c.drawRightString(_PAGE_W - 30, _PAGE_H - _HEADER_H / 2 - 10, label)

    # Texto del cuerpo
    font, font_size = "Helvetica", 38
    max_w = _PAGE_W - 2 * _BODY_MARGIN
    lines = _wrap(texto, font, font_size, max_w)
    line_h = font_size * 1.35
    body_top = _PAGE_H - _HEADER_H - _BODY_MARGIN
    body_bottom = _BODY_MARGIN
    block_h = len(lines) * line_h
    y = body_top - (body_top - body_bottom - block_h) / 2

    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont(font, font_size)
    for line in lines:
        c.drawString(_BODY_MARGIN, y, line)
        y -= line_h


def _generar_logo_png():
    """Crea logo_temp.png con el texto 'UpAndalus' en verde sobre fondo transparente."""
    font_size = 42
    try:
        font = ImageFont.truetype("Helvetica Bold.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = dummy.textbbox((0, 0), "UpAndalus", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    img = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((4, 4), "UpAndalus", font=font, fill="#15944f")

    os.makedirs("assets", exist_ok=True)
    img.save(LOGO_PNG)


def generar_pdf_carrusel(carrusel_texto: str, output_path: str = None) -> str:
    if output_path is None:
        output_path = f"carrusel_{date.today().isoformat()}.pdf"

    _generar_logo_png()

    ideas = _parsear_carrusel(carrusel_texto)
    c = rl_canvas.Canvas(output_path, pagesize=(_PAGE_W, _PAGE_H))

    for idea in ideas:
        slides = idea["slides"]
        total = len(slides)
        for i, texto_slide in enumerate(slides, 1):
            _dibujar_slide(c, texto_slide, i, total)
            c.showPage()

    c.save()
    return output_path


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


def _llamar_claude(
    noticias_bot: list,
    noticias_brave: list,
    cracks_texto: str,
    emails_gmail: list,
) -> dict:
    from datetime import datetime
    payload = {
        "fecha_semana": datetime.now().strftime("%Y-%m-%d"),
        "noticias_telegram": [n["texto"] for n in noticias_bot],
        "noticias_buscadas": [
            {"titulo": n["titulo"], "url": n["url"], "descripcion": n["descripcion"]}
            for n in noticias_brave[:50]
        ],
        "emails_gmail": emails_gmail,
        "transcripcion_cracks": cracks_texto or None,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

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


async def leer_gmail_alerts():
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json:
        print("AVISO: GOOGLE_CREDENTIALS_JSON no configurado, saltando Gmail")
        return []
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        import base64
        from datetime import datetime, timedelta
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"]
        )
        service = build("gmail", "v1", credentials=credentials)
        hace_7_dias = int((datetime.now() - timedelta(days=7)).timestamp())
        query = f'subject:"Alerta de Google" after:{hace_7_dias}'
        results = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        messages = results.get("messages", [])
        textos = []
        for msg in messages:
            full = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            payload = full.get("payload", {})
            parts = payload.get("parts", [payload])
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        texto = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        textos.append(texto)
        return textos
    except Exception as e:
        print(f"Error leyendo Gmail: {e}")
        return []


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

    # Paso 1e: alertas de Gmail
    emails_gmail = await leer_gmail_alerts()

    # Paso 1f: deduplicar contra histórico
    noticias_brave = _deduplicar(noticias_brave, publicadas)

    # Paso 2: generar con Claude
    try:
        output = _llamar_claude(noticias_bot, noticias_brave, cracks_texto, emails_gmail)
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

    # Generar PDF del carrusel
    try:
        generar_pdf_carrusel(output.get("carrusel", ""))
    except Exception as e:
        print(f"Aviso: no se pudo generar el PDF del carrusel: {e}")

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
