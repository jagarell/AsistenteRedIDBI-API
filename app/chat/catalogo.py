"""Catálogo de preguntas del Chat IA para «Preguntas y reglas» (doc 0.0.7 §11 y §48).

El flujo vigente se arma en `app.chat.sim.flow.build(respuestas)`: cada pregunta aparece según lo respondido antes. Para mostrar
al administrador todas las preguntas, sus secciones y su orden, se arma el flujo con las respuestas de una evaluación de ejemplo
(restobar con todo respondido) y se reduce a una ficha por pregunta (las repetidas por caja o impresora, `P22#2`, cuentan una vez).
Así el catálogo siempre coincide con el motor y no hay una segunda lista que mantener.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.chat.flow_engine import BLOCK_LABELS, BLOCK_ORDER
from app.chat.sim.flow import build

TIPOS = {
    "text": "Texto", "longtext": "Texto largo", "date": "Fecha", "choice": "Opción", "multi": "Varias opciones",
    "ev": "Evidencia (foto)", "check": "Fotos por ítem", "rcard": "Datos leídos de las fotos", "links": "Enlaces",
    "pasos": "Pasos a seguir", "summary": "Resumen", "wifi": "Medición WiFi",
}
MUESTRA = Path(__file__).parent / "sim" / "muestra_catalogo.json"


@lru_cache(maxsize=1)
def catalogo() -> Dict[str, Any]:
    respuestas = json.loads(MUESTRA.read_text(encoding="utf-8"))["A"]
    nodos, _ = build(respuestas, {"technician": "Técnico de prueba"})
    vistos: set = set()
    por_seccion: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BLOCK_ORDER}
    for n in nodos:
        base = str(n["id"]).split("#")[0]
        if base in vistos or n.get("kind") in ("alert", "fin") or n.get("b") not in por_seccion:
            continue
        vistos.add(base)
        opts = [str(o.get("l", o.get("v"))) for o in (n.get("opts") or []) if isinstance(o, dict)]
        por_seccion[n["b"]].append({
            "id": base,
            "orden": len(por_seccion[n["b"]]) + 1,
            "texto": n.get("text") or "",
            "tipo": TIPOS.get(n.get("kind"), n.get("kind")),
            "evidencia": n.get("kind") in ("ev", "check", "rcard"),
            "opciones": opts,
            "opcional": n.get("kind") in ("links", "wifi") or (n.get("kind") == "date" and not n.get("req")),
        })
    secciones = [{"id": b, "nombre": BLOCK_LABELS[b], "preguntas": por_seccion[b]} for b in BLOCK_ORDER if por_seccion[b]]
    return {"secciones": secciones, "total": sum(len(s["preguntas"]) for s in secciones)}
