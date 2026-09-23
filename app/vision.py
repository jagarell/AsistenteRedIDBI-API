"""Análisis de fotos de evidencia técnica vía OpenAI Vision. Reutiliza el
mismo seam OPENAI_API_KEY/OPENAI_MODEL que app.chat.engine. Si no hay API key
configurada, o la llamada falla, devuelve un mensaje explícito en vez de
inventar datos.

Para categorías de equipo (router/switch/servers/pos/printer/camera/computer)
además intenta extraer marca/modelo en JSON estructurado, para que
app.chat.proposal pueda contrastarlos contra lo autorreportado en el chat
(ver `detected_equipment` en generate_proposal/compute_analysis).
"""
import json

from pydantic import BaseModel

from app.chat.config import settings


class PhotoAnalyzeRequest(BaseModel):
    category: str
    imageBase64: str


class PhotoAnalyzeResult(BaseModel):
    description: str
    brand: str | None = None
    model: str | None = None


_CATEGORY_LABELS = {
    "router": "un router/módem de red",
    "switch": "un switch de red",
    "pos": "un equipo POS/caja",
    "printer": "una impresora/ticketera",
    "camera": "una cámara de seguridad",
    "computer": "una computadora/laptop",
    "access_point": "un access point WiFi",
    "kitchen": "el área de cocina de un local gastronómico",
    "hall": "el salón/comedor de un local gastronómico",
    "servers": "un rack o gabinete de servidores/networking",
    "area": "una zona del local (evidencia general del área, no un equipo específico)",
    "otro": "un elemento de infraestructura de red",
    "plan": "un plano de local",
    "topology": "un diagrama de topología de red",
}

# Categorías donde vale la pena pedirle al modelo marca/modelo estructurados
# (equipos con etiqueta física legible); para áreas/documentos alcanza con
# la descripción libre.
_EQUIPMENT_CATEGORIES = {
    "router", "switch", "pos", "printer", "camera", "computer",
    "access_point", "servers",
}


# ~15MB de imagen real (el base64 pesa ~4/3 de eso) — bien por encima de lo
# que sube la app hoy (comprime a máx. 2048px/JPEG 90, normalmente <1MB),
# pero evita mandarle a OpenAI un payload gigante si algo en el camino no se
# comprimió como se esperaba.
_MAX_IMAGE_BASE64_CHARS = 20_000_000


def _fallback(message: str) -> PhotoAnalyzeResult:
    return PhotoAnalyzeResult(description=message)


def analyze_photo(category: str, image_base64: str) -> PhotoAnalyzeResult:
    if not settings.openai_api_key:
        return _fallback("Análisis de IA no configurado (falta OPENAI_API_KEY).")

    if len(image_base64) > _MAX_IMAGE_BASE64_CHARS:
        return _fallback("La foto es demasiado pesada para analizarla.")

    label = _CATEGORY_LABELS.get(category, "un elemento de infraestructura de red")
    is_equipment = category in _EQUIPMENT_CATEGORIES

    try:
        from openai import OpenAI  # import diferido: solo se requiere aquí

        client = OpenAI(api_key=settings.openai_api_key)

        if is_equipment:
            prompt_text = (
                f"Esta foto debería mostrar {label}. Identifica marca y modelo "
                "SOLO si el texto es legible en la imagen; no los inventes ni "
                "los adivines si no se ven con claridad — en ese caso usa null. "
                "Responde exclusivamente un JSON con este formato exacto: "
                '{"description": "1-3 frases sobre estado del cableado, '
                'ubicación, estado físico del equipo", "brand": "marca o null", '
                '"model": "modelo o null"}'
            )
        else:
            prompt_text = (
                f"Esta foto debería mostrar {label}. Describe en 1-3 frases lo "
                "que observas (estado del cableado, ubicación, estado físico "
                "del equipo o del área)."
            )

        create_kwargs = {
            "model": settings.openai_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 300,
        }
        if is_equipment:
            create_kwargs["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**create_kwargs)
        text = (completion.choices[0].message.content or "").strip()

        if not is_equipment:
            return PhotoAnalyzeResult(description=text or "No se pudo generar una descripción.")

        try:
            data = json.loads(text)
        except ValueError:
            # El modelo no devolvió JSON válido: no lo descartamos, lo
            # mostramos como descripción libre en vez de fallar.
            return PhotoAnalyzeResult(description=text or "No se pudo generar una descripción.")

        return PhotoAnalyzeResult(
            description=(data.get("description") or "").strip() or "No se pudo generar una descripción.",
            brand=(data.get("brand") or None),
            model=(data.get("model") or None),
        )
    except Exception as exc:  # noqa: BLE001
        return _fallback(f"No se pudo analizar la foto ({exc}).")
