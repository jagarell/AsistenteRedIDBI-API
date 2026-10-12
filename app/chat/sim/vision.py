"""Revisión con IA de cada foto del chat: ¿es lo que se pidió?, ¿se lee?, y qué datos trae.

Por cada evidencia la IA responde primero `esEvidenciaSolicitada` (con `queMuestra`) y `legible`, y luego los datos
(con los mismos nombres que usa el simulador: d1, d2, u, p, pd, pu, ip, gw, marca, modelo, sn...). Sin API key o ante
cualquier falla no se inventa nada: la lectura queda vacía y el técnico la completa a mano.

La etiqueta del router (E2e) trae usuario, contraseña, SSID, clave WLAN y QR: esas regiones se desenfocan con Pillow
antes de devolver la imagen y el original no se guarda (igual que antes con E3).
"""
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.chat.config import settings
from app.chat.evidence import _pixelate_all, _redact
from app.vision import _MAX_IMAGE_BASE64_CHARS, _clean_detected_field

logger = logging.getLogger("idbi.sim.vision")

# Qué se espera ver por tipo de lectura.
TARGETS: Dict[str, str] = {
    "speed": "la captura de pantalla (o foto de la pantalla) del resultado de una prueba de velocidad de internet (speedtest.net, fast.com u otra), con descarga, subida y ping",
    "chip": "la captura de una prueba de velocidad de internet hecha desde un celular con chip de datos",
    "ipconfig": "la salida del comando ipconfig de Windows con la IP, la máscara y la puerta de enlace",
    "scanner": "la captura de un escáner de red o de IP (Advanced IP Scanner u otro) con la lista de equipos encontrados, sus IP, MAC y fabricante",
    "label": "la etiqueta de una impresora térmica donde se ve el modelo y el número de serie",
    "conn": "la parte de atrás de una impresora donde se ven sus conexiones (puerto de red, USB, energía)",
    "selftest": "la hoja de prueba (selftest) impresa por una impresora térmica con su marca, modelo, IP, MAC y puerta de enlace",
    "selftestUsb": "la hoja de prueba (selftest) impresa por una impresora térmica con su marca y modelo",
    "anydesk": "la pantalla del programa AnyDesk abierto con el código de acceso",
    "ports": "el router o módem de internet con todos sus puertos a la vista",
    "routerlabel": "la etiqueta de un router o módem con su marca, modelo y número de serie",
    "photo": "una foto del lugar o equipo pedido",
}

# datos que se piden por lectura: clave -> descripción
FIELDS: Dict[str, Dict[str, str]] = {
    "speed": {
        "d1": "velocidad de BAJADA (descarga) de la prueba 1 en Mbps (número). Ignora la publicidad de planes (\"Plan regular 500 Mbps\", \"1000 Mbps\")",
        "d2": "velocidad de bajada de la prueba 2 en Mbps (número) si hay una segunda prueba, si no null",
        "u": "velocidad de SUBIDA en Mbps (número)",
        "p": "ping en reposo en ms (número)",
        "pd": "ping durante la descarga en ms (número), si aparece",
        "pu": "ping durante la subida en ms (número), si aparece",
        "proveedor": "proveedor de internet (ISP) del usuario; NO el servidor de la prueba",
        "servidor": "servidor contra el que se hizo la prueba (ciudad/empresa)",
        "banda": 'banda WiFi si se ve en la barra de estado ("5" junto al ícono WiFi = 5 GHz), si no null',
    },
    "chip": {"d": "bajada en Mbps (número)", "u": "subida en Mbps (número)", "p": "ping en ms (número)"},
    "ipconfig": {"ip": "dirección IPv4 del adaptador activo", "mascara": "máscara de subred",
                 "gw": "puerta de enlace predeterminada", "adaptador": 'tipo del adaptador activo: "WiFi" o "Ethernet"'},
    "scanner": {
        "equipos": "cantidad de equipos listados (número)",
        "impresoras": "IP de las impresoras (fabricante Epson, Bixolon, Star, 3nStar, Xprinter, POSD) separadas por coma",
        "otros": "otros equipos relevantes con su IP, en texto corto (router, PC, etc.)",
        "cam": 'si hay cámaras: "DVR" si aparece un solo equipo de cámaras con una IP (por ejemplo Hikvision), "NVR" si aparecen varias IP de cámaras, "" si no hay',
        "camIps": "cantidad de IP de cámaras (número, 0 si no hay)",
        "dispositivos": "lista de objetos {ip, mac, fabricante, nombre} con TODOS los dispositivos legibles",
    },
    "label": {"marca": "marca", "modelo": "modelo", "sn": "número de serie (SN)"},
    "conn": {"ver": 'conexión que se ve conectada: "RED" (cable de red RJ45), "USB" (cable USB), "WIFI" (ninguno de los dos) o "NONE" (no se ven las conexiones)'},
    "selftest": {"marca": "marca", "modelo": "modelo", "ip": "dirección IP", "mac": "dirección MAC", "gw": "puerta de enlace (gateway)"},
    "selftestUsb": {"marca": "marca", "modelo": "modelo"},
    "anydesk": {"codigo": "código de AnyDesk (el número de acceso)", "equipo": "nombre o tipo del equipo si aparece"},
    "ports": {
        "puertos": "cantidad de puertos LAN (Ethernet) del router, sin contar WAN/PON, USB ni energía (número)",
        "ocupados": "cuántos de esos puertos LAN tienen un cable conectado (número)",
        "libres": "cuántos de esos puertos LAN están libres, sin cable (número)",
    },
    "routerlabel": {"marca": "marca", "modelo": "modelo", "sn": "número de serie (SN)"},
    "photo": {},
}
NUMERIC = {"d1", "d2", "u", "p", "pd", "pu", "d", "equipos", "camIps", "puertos", "ocupados", "libres"}


class VisionResult(BaseModel):
    corresponde: Optional[bool] = None   # None = no se pudo revisar (sin IA)
    legible: Optional[bool] = None
    queMuestra: Optional[str] = None
    data: Dict[str, Any] = {}
    unavailable: bool = False
    processedImages: Optional[List[str]] = None


def _number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    try:
        f = float(str(value).replace(",", "."))
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _normalize(read: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in FIELDS.get(read, {}):
        v = raw.get(key)
        if key == "dispositivos":
            out[key] = [{k: _clean_detected_field(d.get(k)) for k in ("ip", "mac", "fabricante", "nombre")}
                        for d in (v or []) if isinstance(d, dict)]
        elif key in NUMERIC:
            n = _number(v)
            if n is not None:
                out[key] = n
        elif isinstance(v, str):
            c = _clean_detected_field(v)
            if c is not None:
                out[key] = c
        elif v is not None:
            out[key] = v
    if read == "scanner" and "impresoras" not in out:
        out["impresoras"] = ""
    if read == "ports" and out.get("libres") is None and out.get("puertos") is not None and out.get("ocupados") is not None:
        out["libres"] = max(0, out["puertos"] - out["ocupados"])
    if read == "ports" and out.get("ocupados") is None and out.get("puertos") is not None and out.get("libres") is not None:
        out["ocupados"] = max(0, out["puertos"] - out["libres"])
    return out


def _unavailable(read: str, images: List[str], why: str) -> VisionResult:
    logger.info("Lectura %s sin IA: %s", read, why)
    r = VisionResult(unavailable=True, data={})
    if read == "routerlabel":
        r.processedImages = [_pixelate_all(i) for i in images]
    return r


def analyze(read: str, name: str, images_b64: List[str]) -> VisionResult:
    """Revisa 1 a 3 fotos de la misma evidencia."""
    images_b64 = [i for i in images_b64 if i]
    if not images_b64:
        return VisionResult(corresponde=False, legible=False)
    if not settings.openai_api_key:
        return _unavailable(read, images_b64, "IA no configurada")
    if any(len(i) > _MAX_IMAGE_BASE64_CHARS for i in images_b64):
        return _unavailable(read, images_b64, "foto demasiado pesada")

    target = TARGETS.get(read, TARGETS["photo"])
    fields = FIELDS.get(read, {})
    lines = [
        f'- "esEvidenciaSolicitada": true si las imágenes muestran {target}{f" ({name})" if name else ""}; false si muestran otra cosa (por ejemplo una silla, una pared o una captura de otra app)',
        '- "queMuestra": en pocas palabras, lo que realmente muestra la imagen (para decirle al técnico "se parece a …")',
        '- "legible": true si se leen con claridad los datos que se piden; false si la foto está borrosa, cortada u oscura',
    ] + [f'- "{k}": {v}' for k, v in fields.items()]
    extra = ""
    if read == "routerlabel":
        extra = (
            " IMPORTANTE: NO leas ni transcribas usuario, contraseña, SSID ni clave WiFi/WLAN. Además devuelve \"redacciones\": "
            'lista de regiones {"imagen": índice desde 0, "x": 0-1, "y": 0-1, "w": 0-1, "h": 0-1} que cubran TODO lo que sea usuario, '
            "contraseña, SSID, clave WLAN/WiFi o código QR/de barras de acceso."
        )
    prompt = (
        "Revisas una evidencia técnica que sube un técnico de campo. Extrae SOLO lo claramente legible; si no se ve con claridad usa null: "
        "no inventes ni adivines. Responde exclusivamente un JSON con estas claves:\n" + "\n".join(lines) + extra
    )
    try:
        from openai import OpenAI  # import diferido

        client = OpenAI(api_key=settings.openai_api_key)
        content: List[dict] = [{"type": "text", "text": prompt}]
        for img in images_b64:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{img}", **({"detail": "high"} if read == "scanner" else {})}})
        completion = client.chat.completions.create(
            model=settings.openai_model, messages=[{"role": "user", "content": content}],
            max_tokens=2500 if read == "scanner" else 600, response_format={"type": "json_object"})
        raw = json.loads((completion.choices[0].message.content or "").strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falló la revisión de la evidencia %s: %s", read, exc)
        return _unavailable(read, images_b64, "servicio de IA no disponible")

    corresponde = raw.get("esEvidenciaSolicitada")
    legible = raw.get("legible")
    result = VisionResult(
        corresponde=None if corresponde is None else bool(corresponde),
        legible=None if legible is None else bool(legible),
        queMuestra=_clean_detected_field(raw.get("queMuestra")),
        data=_normalize(read, raw),
    )
    if read == "routerlabel":
        result.processedImages = _redact(images_b64, raw.get("redacciones"))
    return result
