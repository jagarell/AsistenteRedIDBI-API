"""Lectura con IA de las evidencias que el técnico sube desde el chat (E1..E9 y
las EU-* del subflujo de ubicación).

Cada código tiene su propio esquema de campos (ver aiExtract en el flujo).
Mismas reglas que app.vision: sin API key o ante cualquier falla se responde
un resultado honesto (campos vacíos + descripción), nunca datos inventados.

E3 (etiqueta del router) es especial: la etiqueta trae usuario, contraseña,
SSID, clave WLAN y QR. El modelo marca esas regiones y acá se desenfocan con
Pillow ANTES de devolver la imagen; el original nunca se guarda. Si no se
pueden ubicar las regiones (IA no disponible), la imagen se pixela completa
— prefiere perder la foto a filtrar credenciales.
"""
import base64
import io
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.chat.config import settings
from app.vision import _MAX_IMAGE_BASE64_CHARS, _clean_detected_field

logger = logging.getLogger("idbi.evidence")

_EVIDENCE_LABELS = {
    "E1": "la captura de una prueba de velocidad de internet (speedtest.net, fast.com u otra)",
    "E2": "un router/módem de internet en el lugar donde está instalado",
    "E3": "la etiqueta de un router, módem o switch",
    "E4": "la salida del comando ipconfig de Windows",
    "E5": "el ticket de autoprueba (self-test) o la etiqueta de una impresora térmica",
    "E6": "puntos de red (rosetas, patch panel) y tomas de energía",
    "E7": "una extensión/regleta de energía con equipos conectados",
    "E8": "la captura de un escáner de red/IP (lista de dispositivos con IP, MAC y fabricante)",
    "E9": "una vista general del local",
    "EU-R": "un punto de red cercano al lugar donde irá un equipo",
    "EU-RN": "el lugar donde se instalará un punto de red nuevo",
    "EU-E": "una toma de energía cercana al lugar donde irá un equipo",
    "EU-EN": "el lugar donde se instalará una toma de energía nueva",
}

# Campos que se piden por código (nombre → qué es). `descripcion` siempre se pide.
_FIELDS: Dict[str, Dict[str, str]] = {
    "E1": {
        "bajadaMbps": "velocidad de bajada en Mbps (número)",
        "subidaMbps": "velocidad de subida en Mbps (número)",
        "pingMs": "ping en reposo en ms (número)",
        "latenciaBajadaMs": "latencia bajo carga durante la bajada en ms (número), si aparece",
        "latenciaSubidaMs": "latencia bajo carga durante la subida en ms (número), si aparece",
        "proveedor": "nombre del proveedor de internet (ISP) del usuario; NO es el servidor de la prueba "
                     "(en speedtest.net el ISP aparece en la fila del ícono de globo, debajo del servidor)",
        "servidor": "servidor contra el que se hizo la prueba (ciudad/empresa del servidor)",
        "fechaHora": "fecha y hora de la prueba",
    },
    "E2": {"marca": "marca visible", "modelo": "modelo visible", "ubicacionVisual": "dónde está instalado"},
    "E3": {
        "marca": "marca", "modelo": "modelo", "numeroSerie": "número de serie (SN)",
        "mac": "dirección MAC del equipo", "ipGestion": "IP o URL de gestión impresa en la etiqueta",
    },
    "E4": {
        "ipv4": "dirección IPv4 del adaptador activo", "mascara": "máscara de subred",
        "puertaEnlace": "puerta de enlace predeterminada",
        "adaptador": 'tipo del adaptador ACTIVO: "WiFi" o "Ethernet"',
        "mac": "dirección física (MAC) del adaptador activo",
        "nombreEquipo": "nombre del equipo si aparece",
        "ethernetDesconectado": "true si el adaptador Ethernet figura 'medios desconectados', si no false",
    },
    "E5": {
        "marca": "marca", "modelo": "modelo", "numeroSerie": "número de serie",
        "ip": "dirección IP", "mascara": "máscara de subred", "puertaEnlace": "gateway",
        "dhcp": "true si DHCP está activado, false si está desactivado, null si no se ve",
        "mac": "dirección MAC", "puerto": "puerto de impresión (ej. 9100)",
        "papel": "ancho de papel (ej. 72 mm)", "interfaz": "interfaces (ej. Ethernet y USB)",
    },
    "E6": {"estadoCableado": "estado del cableado", "rotulado": "true/false si los cables están rotulados",
           "observaciones": "observaciones relevantes"},
    "E7": {"equiposConectados": "equipos conectados a la extensión (lista de textos)",
           "estado": "estado físico", "riesgo": "riesgo eléctrico observado"},
    "E8": {"dispositivos": "lista de objetos {ip, mac, fabricante, nombre} con TODOS los dispositivos legibles"},
    "E9": {},
    "EU-R": {"estado": "estado del punto de red", "rotulado": "true/false si está rotulado"},
    "EU-RN": {},
    "EU-E": {"estado": "estado de la toma", "tipoToma": "tipo de toma"},
    "EU-EN": {},
}

_MAX_TOKENS = {"E8": 2500, "E5": 700, "E4": 600}


class EvidenceResult(BaseModel):
    code: str
    extracted: Dict[str, Any] = {}
    # Solo E3: imágenes ya con las credenciales desenfocadas (base64 JPEG).
    processedImages: Optional[List[str]] = None


def _fallback_result(code: str, reason: str, images: List[str]) -> EvidenceResult:
    result = EvidenceResult(
        code=code,
        extracted={"descripcion": f"Lectura automática no disponible ({reason}). "
                                  "Revisa la foto a mano y anota los datos."},
    )
    if code == "E3":
        result.processedImages = [_pixelate_all(i) for i in images]
    return result


def analyze_evidence(code: str, images_b64: List[str]) -> EvidenceResult:
    """Lee una o varias fotos (máx. 3) de la misma evidencia."""
    images_b64 = [i for i in images_b64 if i]
    if not images_b64:
        return EvidenceResult(code=code, extracted={})
    if not settings.openai_api_key:
        return _fallback_result(code, "IA no configurada", images_b64)
    if any(len(i) > _MAX_IMAGE_BASE64_CHARS for i in images_b64):
        return _fallback_result(code, "la foto es demasiado pesada", images_b64)

    label = _EVIDENCE_LABELS.get(code, "una evidencia de infraestructura de red")
    fields = _FIELDS.get(code, {})
    lines = [f'- "{k}": {v}' for k, v in fields.items()]
    lines.append('- "descripcion": 1-2 frases sobre lo que muestra la imagen')
    extra = ""
    if code == "E3":
        extra = (
            " IMPORTANTE: NO leas ni transcribas usuario, contraseña, SSID ni clave WiFi/WLAN. "
            'Además devuelve "redacciones": lista de regiones {"imagen": índice desde 0, '
            '"x": 0-1, "y": 0-1, "w": 0-1, "h": 0-1} (fracciones del ancho/alto) que cubran '
            "TODO lo que sea usuario, contraseña, SSID, clave WLAN/WiFi o código QR/de barras de acceso."
        )
    prompt = (
        f"Estas imágenes muestran {label}. Extrae SOLO lo claramente legible; si no se ve "
        "con claridad usa null — no inventes ni adivines. Responde exclusivamente un JSON "
        "con estas claves:\n" + "\n".join(lines) + extra
    )

    try:
        from openai import OpenAI  # import diferido

        client = OpenAI(api_key=settings.openai_api_key)
        content: List[dict] = [{"type": "text", "text": prompt}]
        for img in images_b64:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{img}",
                # El escáner de IP es una tabla densa: en detalle alto se leen más filas.
                **({"detail": "high"} if code == "E8" else {}),
            }})
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": content}],
            max_tokens=_MAX_TOKENS.get(code, 500),
            response_format={"type": "json_object"},
        )
        text = (completion.choices[0].message.content or "").strip()
        data = json.loads(text)
    except ValueError:
        return _fallback_result(code, "la IA no devolvió un formato válido", images_b64)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fallo la lectura de evidencia %s: %s", code, exc)
        return _fallback_result(code, "servicio de IA no disponible en este momento", images_b64)

    extracted = _normalize(code, data)
    result = EvidenceResult(code=code, extracted=extracted)
    if code == "E3":
        result.processedImages = _redact(images_b64, data.get("redacciones"))
    return result


def _normalize(code: str, data: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in list(_FIELDS.get(code, {})) + ["descripcion"]:
        value = data.get(key)
        if key == "dispositivos":
            devices = []
            for d in value or []:
                if isinstance(d, dict):
                    devices.append({k: _clean_detected_field(d.get(k)) for k in ("ip", "mac", "fabricante", "nombre")})
            out[key] = devices
        elif isinstance(value, str):
            out[key] = _clean_detected_field(value)
        elif value is not None:
            out[key] = value
    if not out.get("descripcion"):
        out["descripcion"] = "No se pudo generar una descripción."
    return out


# ---- redacción de credenciales (E3) --------------------------------------
def _decode(b64: str):
    from PIL import Image  # import diferido

    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _encode(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _pixelate_all(b64: str) -> str:
    try:
        img = _decode(b64)
        w, h = img.size
        small = img.resize((max(1, w // 40), max(1, h // 40)))
        return _encode(small.resize((w, h)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo pixelar la imagen: %s", exc)
        return ""


def _redact(images_b64: List[str], regions: Any) -> List[str]:
    from PIL import ImageFilter

    boxes: Dict[int, List[dict]] = {}
    for r in regions or []:
        if isinstance(r, dict):
            boxes.setdefault(int(r.get("imagen", 0) or 0), []).append(r)

    processed: List[str] = []
    for idx, b64 in enumerate(images_b64):
        rs = boxes.get(idx)
        if not rs:
            # El modelo no marcó nada en esta imagen: ante la duda, se pixela
            # completa (una etiqueta sin regiones marcadas no se puede garantizar limpia).
            processed.append(_pixelate_all(b64))
            continue
        try:
            img = _decode(b64)
            w, h = img.size
            for r in rs:
                pad = 0.01
                x0 = max(0, int((float(r["x"]) - pad) * w))
                y0 = max(0, int((float(r["y"]) - pad) * h))
                x1 = min(w, int((float(r["x"]) + float(r["w"]) + pad) * w))
                y1 = min(h, int((float(r["y"]) + float(r["h"]) + pad) * h))
                if x1 <= x0 or y1 <= y0:
                    continue
                region = img.crop((x0, y0, x1, y1))
                region = region.resize((max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12))).resize(region.size)
                region = region.filter(ImageFilter.GaussianBlur(8))
                img.paste(region, (x0, y0))
            processed.append(_encode(img))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falló la redacción de la imagen %s: %s", idx, exc)
            processed.append(_pixelate_all(b64))
    return processed
