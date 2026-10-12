"""Análisis IA a partir del estado del chat nuevo (4 tarjetas con criterios ponderados, resumen y Referencias)."""
import json
from typing import Any, Dict, List, Optional

from app.chat.sim.engine import Session
from app.chat.sim.rules import gen_pasos
from app.chat.sim.scoring import card_desc, lvl, ref_data, ref_rub, ref_why, resumen_ia, scores

_COLOR = {"st-o": "green", "st-b": "blue", "st-r": "orange", "st-d": "red", "st-n": "gray"}


def analyze_state(state: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    s = Session(state)
    X, R = s.X, s.R
    sc = s.scores()
    results: List[Dict[str, Any]] = []
    for c in sc.cards:
        lv = lvl(c.v)
        results.append({
            "title": c.k, "status": lv["label"], "score": c.v, "description": card_desc(c, X, R), "color": _COLOR[lv["cls"]],
            "criteria": [{"name": q.k, "weight": q.w, "compliance": q.r, "detail": q.d} for q in (c.crit or [])],
            "why": c.why,
        })
    refs = ref_data(X, R)
    return {
        "globalScore": sc.g, "evaluatedAreas": sc.areas, "attentionRequired": sc.att, "results": results,
        "summary": resumen_ia(X, R, name),
        "asIsFindings": [i.t for i in R.it if i.tipo != "REC"],
        "recommendations": [f"{i.t}. {i.d}" for i in R.it if i.tipo != "AVISO"],
        "estado": R.estado,
        "recommendationItems": [{"id": i.id, "type": i.tipo, "title": i.t, "detail": i.d, "equipment": i.eq} for i in R.it],
        "steps": gen_pasos(X, R, s.A),
        "references": {
            "similar": [{"name": x["n"], "rubro": ref_rub(x["rub"]), "pct": x["pct"], "why": ref_why(x)} for x in refs["top"]],
            "recommendations": refs["recs"],
            "suggested": refs["sug"],
        },
    }
