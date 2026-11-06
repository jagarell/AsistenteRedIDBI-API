"""Lectura de texto libre del técnico (Chat IA al terminar y Asistente IA): contraseñas, puertos del switch,
ubicación del router y pedidos de cambio de criterio. Port de cred48, ports47, det45 y CRIT47 del simulador."""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import det45

ROUTER45 = re.compile(r"router|m[oó]dem", re.I)
CRIT47 = re.compile(
    r"(todas las minutas|toda minuta|cada minuta|las minutas (deben|debe|tienen)|de ahora en adelante|en adelante|desde ahora|"
    r"para todos los locales|siempre (debe|deben|que)|nunca (debe|deben)|cambi\w* (la|las|el|los) (regla|reglas|formato|plantilla|criterio|texto)|"
    r"(las|la) recomendaci\w* (debe|deben|tienen|tiene)|el resumen ejecutivo (no )?debe|la minuta (no )?(debe|deber[ií]a)\b)", re.I)
SENT = re.compile(r"(?<=[a-z0-9áéíóúñ)\]][.;])\s+")


def sentences(t: str) -> List[str]:
    """Separa en oraciones sin cortar «IMP. Caja» ni las IP."""
    return [x for x in SENT.split(str(t or "")) if x.strip()]


def credencial(t: str) -> Optional[Dict[str, str]]:
    """«la contraseña del wifi MOVISTAR_F653 es …», «portal web de la IMP. Caja: usuario admin contraseña 123»."""
    t = str(t or "").strip().rstrip(".;")
    if not re.search(r"contrase[ñn]a|clave|password", t, re.I):
        return None
    m = (re.search(r"(?:contrase[ñn]a|clave|password)(?:\s+(?:del?|de la)\s+[^:=]{1,40}?)?\s*(?:es|:|=)\s*[\"«]?([^\s\"»,;]+)", t, re.I)
         or re.search(r"(?:contrase[ñn]a|clave|password)\s*:?\s*[\"«]?([^\s\"»,;]+)", t, re.I))
    pw = m.group(1) if m else None
    if not pw or re.fullmatch(r"del?|de|la|el|es", pw, re.I):
        return None
    usr = (re.search(r"usuario\s*(?:es|:|=)?\s*[\"«]?([^\s\"»,;]+)", t, re.I) or [None, ""])[1] or ""
    red = (re.search(r"(?:red|wifi|ssid)\s*(?:es|:)?\s*[\"«]?([A-Z0-9][A-Za-z0-9_\-]{3,})", t) or [None, ""])[1] or ""
    imp = re.search(r"IMP\.?\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+(?:\s+(?!usuario|contrase|portal|clave|es\b)[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+){0,2})", t)
    if re.search(r"repetidor", t, re.I):
        eq = "Repetidor WiFi"
    elif imp:
        eq = f"IMP. {imp.group(1).strip()} · portal web"
    elif re.search(r"impresora|portal", t, re.I):
        eq = "Impresora · portal web"
    elif re.search(r"router|m[oó]dem", t, re.I) and not re.search(r"wifi|red\b", t, re.I):
        eq = "Router · portal web"
    elif re.search(r"wifi|red\b", t, re.I):
        eq = "Red WiFi"
    else:
        eq = "Equipo"
    return {"eq": eq, "usr": usr or red, "pw": pw}


def puertos_switch(t: str, printers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """«la IMP. Barra 1 va al puerto 3 del switch de 8 puertos» → [{name, port}] y n."""
    s = str(t or "").lower()
    prs = [p for p in printers if p.get("con") in ("RED", "WIFI")]
    pos = sorted([(p, s.find(str(p.get("name", "")).lower())) for p in prs if s.find(str(p.get("name", "")).lower()) >= 0], key=lambda x: x[1])
    out = []
    for j, (p, i) in enumerate(pos):
        seg = s[i:(pos[j + 1][1] if j + 1 < len(pos) else len(s))]
        m = re.search(r"puerto\s*(?:n[°º.]?\s*)?(\d{1,2})", seg)
        if m:
            out.append({"name": p["name"], "port": int(m.group(1))})
    nm = re.search(r"switch de (\d{1,2}) puertos", s)
    return {"ports": out, "n": int(nm.group(1)) if nm else None} if out else None


def ubicacion_router(t: str) -> Optional[Dict[str, Any]]:
    """Ubicación del router escrita por el técnico → detalle y si es espacio cerrado (MUEBLE / CUARTO)."""
    if not ROUTER45.search(t or ""):
        return None
    d = det45(t)
    if not d:
        return None
    low = t.lower()
    enc = "MUEBLE" if re.search(r"mueble|gabinete|armario|cl[oó]set", low) else "CUARTO" if "cuarto" in low else None
    return {"detalle": " · ".join(d), "enc": enc}


def es_criterio(t: str) -> bool:
    """Pedido que cambia el criterio de todas las minutas: no se aplica desde un chat."""
    return bool(CRIT47.search(t or ""))
