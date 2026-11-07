"""Plan de cambios de una minuta («Actualiza la minuta de …: …»). La app muestra la tarjeta «Cambios que haré» y,
al aplicar, el gateway guarda la nueva versión con historial y la minuta vuelve a validación."""
import re
from typing import Any, Dict, List

from app.asistente.edicion import leer as leer_ediciones
from app.asistente.texto import credencial, es_criterio, puertos_switch, sentences, ubicacion_router


def plan_cambios(texto: str, printers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convierte el texto en ítems: doc (cualquier dato de la minuta: tablas, impresoras, equipos, energía, anexo), router,
    swport, cred, rec, pasoC, pasoT u obs. Un cambio de criterio no se aplica."""
    if es_criterio(texto):
        return {"criterio": True, "items": [],
                "mensaje": "Eso cambia el criterio de todas las minutas (formato, reglas o textos de recomendaciones), no los datos de un local. "
                           "Lo hace el administrador en Preguntas y reglas o el equipo de desarrollo."}
    items: List[Dict[str, Any]] = []
    ops, resto = leer_ediciones(texto)
    items += [{"k": "doc", "v": o, "t": o["t"]} for o in ops]
    if ops:
        # lo que se entendió como datos de la minuta no se vuelve a leer como observación
        texto = " ".join(resto)
        if not texto.strip():
            return {"criterio": False, "items": items}
    # la ubicación del router solo se lee de la frase que habla del router (antes se buscaba en todo el texto)
    frase_router = " ".join(s for s in sentences(texto) if re.search(r"router|m[oó]dem", s, re.I))
    ub = None if any(o["op"] == "routerEnc" for o in ops) else ubicacion_router(frase_router)
    if ub:
        items.append({"k": "router", "v": ub["detalle"], "enc": ub["enc"], "t": ub["detalle"]})
    sp = puertos_switch(texto, printers) if re.search(r"puerto", texto, re.I) else None
    if sp:
        items.append({"k": "swport", "v": sp, "t": " · ".join(f"IMP. {r['name']} → puerto {r['port']}" for r in sp["ports"])})
    for s in sentences(texto):
        s0 = s.strip().rstrip(".;")
        c = credencial(s0)
        if c:
            items.append({"k": "cred", "v": c, "t": f"{c['eq']}{' · ' + c['usr'] if c['usr'] else ''} · contraseña {c['pw']}"})
            continue
        if (ub and re.search(r"router|m[oó]dem", s0, re.I)) or (sp and re.search(r"puerto", s0, re.I)):
            continue
        if re.search(r"\brecomiend", s0, re.I):
            items.append({"k": "rec", "t": s0[0].upper() + s0[1:], "d": ""})
        elif re.search(r"\bel cliente (debe|tiene que|va a|enviar[aá]|confirmar[aá])", s0, re.I):
            items.append({"k": "pasoC", "t": s0[0].upper() + s0[1:] + "."})
        elif re.search(r"equipo t[eé]cnico|segunda visita|volver a visitar", s0, re.I):
            items.append({"k": "pasoT", "t": s0[0].upper() + s0[1:] + "."})
        elif s0:
            items.append({"k": "obs", "t": s0[0].upper() + s0[1:] + "."})
    return {"criterio": False, "items": items}
