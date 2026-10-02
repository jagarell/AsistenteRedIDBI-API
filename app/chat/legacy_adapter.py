"""Puente entre el estado del flujo nuevo y los consumidores anteriores.

`proposal.py`, `topology.py`, `checklist.py` y `analysis.py` (y el gateway,
que guarda las respuestas en la evaluación) leen claves planas del motor
lineal viejo (`establishment_name`, `wifi_zones`, `pos_count`, ...). En vez de
reescribir los 4 en la misma entrega, esta función las deriva del estado
nuevo. Lo que el flujo nuevo no pregunta (metros cuadrados, material de las
paredes, switches) queda vacío — esos módulos ya lo toleran.

Además devuelve claves legibles por campo del flujo (`visita.local`, ...) con
el valor ya en texto, que es lo que muestra la pantalla de Propuesta
(`GET /chat/nodes` + respuestas persistidas).
"""
import json
from typing import Any, Dict, List

from app.chat import checks
from app.chat.flow_engine import FLOW, Session

STATE_KEY = "__state"

_CONNECTION_LEGACY = {
    "FIBRA": "Fibra óptica", "COBRE": "Cable", "INALAMBRICA": "4G/5G", "NO_SE": "",
}


def _text(session: Session, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(session.label_of(v) for v in value)
    if value in ("SI", "NO"):
        return "Sí" if value == "SI" else "No"
    return session.label_of(value) if isinstance(value, str) else str(value)


def readable_answers(state: Dict[str, Any]) -> Dict[str, str]:
    """{field: texto} de las preguntas sin repetición (visita.*, negocio.*,
    internet.*, energia.*, cableado.*, wifi.*, cierre.*...)."""
    s = Session(state)
    out: Dict[str, str] = {}
    for nid, node in FLOW.nodes.items():
        field = node.get("field")
        if not field or node["kind"] != "question" or "[" in field:
            continue
        if nid in state["answers"]:
            out[field] = _text(s, state["answers"][nid])
    return out


def legacy_answers(state: Dict[str, Any]) -> Dict[str, str]:
    s = Session(state)
    a = state["answers"]

    def txt(nid: str) -> str:
        return _text(s, a.get(nid))

    cajas = checks.cajas(state)
    printers = checks.printers_detail(state)
    conns = {p["conexion"] for p in printers if p["conexion"]}
    if "USB" in conns and conns - {"USB"}:
        printer_connection = "Ambos"
    elif conns == {"USB"}:
        printer_connection = "USB"
    else:
        printer_connection = "Puerto de red"

    e3 = checks.first_extracted(state, "E3")
    router = " ".join(x for x in (e3.get("marca"), e3.get("modelo")) if x)

    areas: List[str] = a.get("P11") or []
    out: Dict[str, str] = {
        "establishment_name": txt("P02") or txt("P01"),
        "establishment_type": txt("P09"),
        "address": txt("P03"),
        "internet_provider": txt("P13"),
        "internet_speed": str(a.get("P15", "")),
        "connection_type": _CONNECTION_LEGACY.get(a.get("P14", ""), ""),
        "router_model": router,
        "pos_count": str(a.get("P12", 0)),
        "printer_count": str(len(printers)),
        "printer_connection": printer_connection,
        "camera_count": "1" if a.get("P47") == "SI" else "0",
        "computer_count": str(sum(1 for c in cajas if c["equipo"] in ("PC", "LAPTOP"))),
        "wifi_zones": ", ".join(s.label_of(x) for x in areas),
        "power_outlets": "Sí" if a.get("P33") == "SI" else "No" if a.get("P33") == "NO" else "",
        "has_switches": "",
        "switch_ports": "",
    }
    loc = state["answers"].get("visita.ubicacion")
    if loc:
        out["location"] = loc
    return out


def completed_answers(state: Dict[str, Any]) -> Dict[str, str]:
    """Lo que viaja en `answers` de la respuesta final y que el gateway
    persiste: claves legacy + legibles + el estado completo (para la minuta)."""
    out = legacy_answers(state)
    out.update(readable_answers(state))
    out[STATE_KEY] = json.dumps(state, ensure_ascii=False)
    return out


def partial_answers(state: Dict[str, Any]) -> Dict[str, str]:
    """Respuestas durante el chat (sin el estado: ese viaja aparte)."""
    out = legacy_answers(state)
    out.update(readable_answers(state))
    return out
