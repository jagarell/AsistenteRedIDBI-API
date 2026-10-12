"""Lecturas de la IA: campos editables por tipo de evidencia y su texto en el chat (port de READ_FIELDS / readLabel)."""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import CAT
from app.chat.sim.util import fmt

READ_FIELDS: Dict[str, List[List[Any]]] = CAT["READ_FIELDS"]
CONN_TXT: Dict[str, str] = CAT["CONN_TXT"]


def field_specs(read: str) -> List[Dict[str, Any]]:
    """Campos editables de una lectura, listos para que el cliente arme el formulario."""
    out = []
    for f in READ_FIELDS.get(read, []):
        key, label = f[0], f[1]
        ty = f[2] if len(f) > 2 else "number"
        spec: Dict[str, Any] = {"key": key, "label": label, "type": ty}
        if ty == "sel":
            spec["options"] = [{"value": o[0], "label": o[1]} for o in f[3]]
        out.append(spec)
    return out


def _deleted(d: Optional[Dict[str, Any]], key: Any) -> bool:
    dels = (d or {}).get("_del") or []
    if isinstance(key, list):
        return any(k in dels for k in key)
    return key in dels


def _lower_first(t: str) -> str:
    return t[0].lower() + t[1:] if re.match(r"^[A-ZÁÉÍÓÚ][a-záéíóúñ]", t) else t


def _read_label_gen(read: str, d: Dict[str, Any]) -> str:
    parts: List[str] = []
    for f in READ_FIELDS.get(read, []):
        key, label = f[0], f[1]
        ty = f[2] if len(f) > 2 else None
        if _deleted(d, key) or d.get(key) is None or d.get(key) == "":
            continue
        shown = d[key]
        if ty == "sel":
            shown = next((o[1] for o in f[3] if o[0] == str(d[key])), d[key])
        parts.append(f"{_lower_first(re.sub(r' \(.*\)$', '', label))} {fmt(shown)}")
    return "La IA leyó: " + " · ".join(parts) + "." if parts else "Se eliminaron las lecturas de esta evidencia."


def read_label(read: str, d: Optional[Dict[str, Any]]) -> str:
    d = d or {}
    if d.get("_del"):
        return _read_label_gen(read, d)

    def g(k: str, alt: str = "") -> str:
        v = d.get(k)
        return alt if v is None or v == "" else fmt(v)

    if read == "speed":
        return (f"La IA leyó: prueba 1 {g('d1', '—')} Mbps, prueba 2 {g('d2', '—')} Mbps, subida {g('u', '—')} Mbps, "
                f"ping {g('p', '—')} ms (con descarga {g('pd', '—')} ms, con subida {g('pu', '—')} ms).")
    if read == "chip":
        return f"La IA leyó: descarga {g('d', '—')} Mbps, subida {g('u', '—')} Mbps, ping {g('p', '—')} ms."
    if read == "label":
        return f"La IA leyó: {g('marca', 'marca sin dato')} {g('modelo')}, SN {g('sn', 'sin dato')}."
    if read == "conn":
        return f"La IA ve {CONN_TXT.get(d.get('ver'), 'las conexiones')}."
    if read == "selftest":
        return (f"La IA leyó en el selftest: {g('marca', 'marca sin dato')} {g('modelo')} · IP {g('ip', 'sin dato')} · "
                f"MAC {g('mac', 'sin dato')} · puerta de enlace {g('gw', 'sin dato')}.")
    if read == "selftestUsb":
        return f"La IA leyó en el selftest: {g('marca', 'marca sin dato')} {g('modelo')}. Impresora USB: no tiene IP ni MAC de red."
    if read == "ipconfig":
        return f"La IA leyó: IP {g('ip', 'sin dato')}, máscara {g('mascara', 'sin dato')}, puerta de enlace {g('gw', 'sin dato')}."
    if read == "scanner":
        cam = (" Cámaras: un DVR (una sola IP)." if d.get("cam") == "DVR"
               else f" Cámaras: un NVR con {g('camIps', 'varias')} IP de cámaras." if d.get("cam") == "NVR" else "")
        otros = f" Otros: {d['otros']}." if d.get("otros") else ""
        return f"La IA leyó {g('equipos', '0')} equipos en la red. Impresoras: {g('impresoras', 'ninguna')}.{otros}{cam}"
    if read == "anydesk":
        return f"La IA leyó el código de AnyDesk {g('codigo', 'sin dato')} en {g('equipo', 'el equipo de caja')}."
    if read == "ports":
        return "La IA no pudo leer los puertos libres." if d.get("libres") is None else f"La IA leyó {fmt(d['libres'])} puerto(s) LAN libre(s)."
    return "Foto recibida."
