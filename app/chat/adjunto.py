"""Lectura de documentos del cliente adjuntos en el Chat IA (ficha RUC, comprobante, recibo, tarjeta, letrero)."""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.chat.config import settings

logger = logging.getLogger(__name__)

# tipo -> campos [(nodo, etiqueta, clave que devuelve la IA)]
TIPOS: Dict[str, Dict[str, Any]] = {
    "ruc": {"l": "Ficha RUC o consulta RUC (SUNAT)",
            "f": [("P01", "Razón social", "razonSocial"), ("P01b", "RUC", "ruc"),
                  ("P01c", "Nombre del local", "nombreComercial"), ("P03", "Dirección", "direccion")],
            "off": ["P03"], "nota": "La dirección de la ficha RUC es el domicilio fiscal: márcala solo si es la del local."},
    "comp": {"l": "Boleta o factura del local",
             "f": [("P01", "Razón social", "razonSocial"), ("P01b", "RUC", "ruc"),
                   ("P01c", "Nombre del local", "nombreComercial"), ("P03", "Dirección", "direccion")]},
    "recibo": {"l": "Recibo de internet", "f": [("P13", "Proveedor", "proveedor"), ("P15", "Plan", "planMbps")]},
    "tarjeta": {"l": "Tarjeta o datos del encargado",
                "f": [("P04", "Encargado", "encargado"), ("P05", "Celular", "celular"), ("P05b", "Correo", "correo")]},
    "frontis": {"l": "Foto del frontis o letrero", "f": [("P01c", "Nombre del local", "nombreComercial")]},
}
# pregunta -> tipo sugerido (atajo debajo de la pregunta)
POR_NODO = {"P01": "ruc", "P01b": "ruc", "P01c": "frontis", "P03": "comp", "P04": "tarjeta", "P05": "tarjeta",
            "P05b": "tarjeta", "P13": "recibo", "P15": "recibo"}
PROV = {"movistar": "MOVISTAR", "claro": "CLARO", "entel": "ENTEL", "win": "WIN", "bitel": "BITEL"}


def leer(tipo: Optional[str], images_b64: List[str]) -> Dict[str, Any]:
    """Devuelve {status, tipo, valores{clave: texto}}; status UNAVAILABLE si no hay IA."""
    if not settings.openai_api_key:
        return {"status": "UNAVAILABLE", "tipo": tipo, "valores": {}}
    claves = sorted({c for t in TIPOS.values() for _, _, c in t["f"]})
    prompt = ("Lees un documento de un cliente peruano (ficha RUC de SUNAT, boleta o factura, recibo de internet, tarjeta de presentación "
              "o foto del letrero del local). Extrae SOLO lo claramente legible; si no se ve, usa null. No inventes. Responde un JSON con "
              f'"tipo" (uno de {list(TIPOS)}) y las claves {claves}. "ruc": 11 dígitos sin espacios. "planMbps": número. '
              '"encargado": "Nombre Apellido, cargo". "razonSocial": el nombre legal de la empresa (en la ficha RUC va después del número de RUC y un guion, '
              'por ejemplo «20123456789 - MI EMPRESA S.A.C.»); nunca el tipo de contribuyente ni el tipo de sociedad (SOCIEDAD ANONIMA CERRADA, E.I.R.L. solos). '
              '"nombreComercial": solo si el documento trae un nombre comercial o letrero distinto de la razón social; si dice «-» o no aparece, usa null.')
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        content: List[dict] = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{i}"}} for i in images_b64[:3]]
        r = client.chat.completions.create(model=settings.openai_model, messages=[{"role": "user", "content": content}],
                                           max_tokens=500, response_format={"type": "json_object"})
        raw = json.loads(r.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falló la lectura del adjunto: %s", exc)
        return {"status": "UNAVAILABLE", "tipo": tipo, "valores": {}}
    t = tipo if tipo in TIPOS else (raw.get("tipo") if raw.get("tipo") in TIPOS else None)
    return {"status": "OK", "tipo": t,
            "valores": {k: (None if raw.get(k) in (None, "") else str(raw.get(k)).strip()) for k in claves}}


def campos(tipo: str, valores: Dict[str, Any], respondidas: Dict[str, Any], validar) -> List[Dict[str, Any]]:
    """Filas de la hoja «Datos leídos del adjunto». validar(nodo, valor) -> mensaje de error o ''."""
    t = TIPOS[tipo]
    out = []
    for nodo, etiqueta, clave in t["f"]:
        v = valores.get(clave)
        if v is None:
            continue
        err = validar(nodo, v)
        out.append({"nodeId": nodo, "label": etiqueta, "valor": v, "respondido": respondidas.get(nodo) is not None,
                    "usar": not err and nodo not in t.get("off", []) and respondidas.get(nodo) is None, "error": err or None})
    return out


def a_prefill(campo: Dict[str, Any]) -> Dict[str, Any]:
    """Valor que se guarda en state['pre'] para cuando el chat llegue a la pregunta."""
    nodo, v = campo["nodeId"], str(campo["valor"]).strip()
    if nodo == "P13":
        code = next((c for w, c in PROV.items() if w in v.lower()), None)
        return {"v": code or f"OTRO:{v}", "label": v}
    if nodo == "P15":
        n = re.sub(r"[^\d.]", "", v)
        return {"v": n if n in ("300", "500", "1000") else f"OTRO:{n}", "label": f"{n} Mbps"}
    return {"v": v, "label": v}
