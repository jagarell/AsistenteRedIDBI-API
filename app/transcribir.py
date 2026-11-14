"""Dictado por voz: transcribe en el servidor el audio que graba la app o la web.

El reconocimiento de voz del teléfono (Google) fallaba con términos del oficio (AnyDesk, switch, IP, nombres de áreas);
aquí se usa el modelo de transcripción de OpenAI con una lista de términos como contexto. La clave (OPENAI_API_KEY)
queda en el servidor. Si no hay clave o la llamada falla, se devuelve un mensaje claro en `error` y `text` vacío.
"""
import base64
import io
import logging
import os
from typing import Optional

from pydantic import BaseModel

from app.chat.config import settings

logger = logging.getLogger("idbi.transcribir")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MODELO = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-transcribe")
MODELO_RESPALDO = "whisper-1"

# Contexto que ayuda al modelo con el vocabulario del trabajo en campo.
PISTA = ("Técnico de redes en un local de restaurante en Perú. Términos: AnyDesk, router, switch, repetidor, access point, "
         "WiFi, IP, ipconfig, speedtest, Wrapper, Sunmi, iMin, Raspberry, impresora, ticketera, caja, comandas, cocina, "
         "barra, salón, terraza, RUC, razón social, UPS, punto de red, cable de red, USB.")

_EXT = {"audio/mp4": "m4a", "audio/aac": "aac", "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/mpeg": "mp3",
        "audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav", "video/webm": "webm"}


class TranscribirRequest(BaseModel):
    audioBase64: str
    mime: str = "audio/mp4"


class TranscribirResultado(BaseModel):
    text: str = ""
    error: Optional[str] = None


def transcribir(req: TranscribirRequest) -> TranscribirResultado:
    if not settings.openai_api_key:
        return TranscribirResultado(error="El dictado no está disponible: falta configurar la IA en el servidor.")
    try:
        audio = base64.b64decode(req.audioBase64, validate=False)
    except Exception:
        return TranscribirResultado(error="No se pudo leer el audio. Vuelve a grabarlo.")
    if len(audio) < 800:
        return TranscribirResultado(error="El audio es muy corto. Mantén la grabación un poco más.")
    if len(audio) > MAX_AUDIO_BYTES:
        return TranscribirResultado(error="El audio es muy largo. Graba un mensaje más corto.")

    mime = (req.mime or "audio/mp4").split(";")[0].strip().lower()
    nombre = "audio." + _EXT.get(mime, "m4a")
    try:
        from openai import OpenAI  # import diferido, como en app/vision.py

        client = OpenAI(api_key=settings.openai_api_key, timeout=60)
        ultimo: Optional[Exception] = None
        for modelo in (MODELO, MODELO_RESPALDO):
            try:
                kw = {"prompt": PISTA}
                r = client.audio.transcriptions.create(model=modelo, file=(nombre, io.BytesIO(audio), mime), language="es", **kw)
                texto = (getattr(r, "text", "") or "").strip()
                if not texto:
                    return TranscribirResultado(error="No se entendió el audio. Habla más cerca del micrófono e inténtalo de nuevo.")
                return TranscribirResultado(text=texto)
            except Exception as e:  # noqa: BLE001 - se prueba el modelo de respaldo
                ultimo = e
                logger.warning("Transcripción con %s falló: %s", modelo, e)
        raise ultimo or RuntimeError("sin respuesta")
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo transcribir: %s", e)
        return TranscribirResultado(error="No se pudo transcribir el audio. Revisa tu conexión e inténtalo de nuevo.")
