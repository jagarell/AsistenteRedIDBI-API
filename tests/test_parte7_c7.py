"""Parte 7 · C7: la apreciación larga del técnico va en Observaciones y no dentro de una tabla."""
import json

from app.chat.sim.engine import Session
from app.chat.sim.minuta import build_document
from tests.test_sim_engine import CASES, run_case


def test_apreciacion_en_observaciones_y_no_en_tablas(monkeypatch):
    caso = next(c for c in CASES if c["name"].startswith("caso 2"))
    r = run_case(caso, monkeypatch)
    s = Session(json.loads(r.state))
    assert s.X.tomas == "NO" and s.X.apreciacion
    doc = build_document(s.A, s.state["ctx"])
    blocks = doc["blocks"]
    # ninguna tabla (clave-valor, tabla o reglas) repite la apreciación
    for b in blocks:
        if b.get("t") == "kv":
            assert all("Apreciaciones" not in r["label"] for r in b["rows"])
        assert s.X.apreciacion not in json.dumps(b.get("rows", ""), ensure_ascii=False)
    i = next(k for k, b in enumerate(blocks) if b.get("t") == "h2" and b.get("text") == "Observaciones")
    assert any(b.get("t") == "para" and b.get("text") == s.X.apreciacion for b in blocks[i + 1:i + 3])


def test_tomas_por_confirmar_llega_a_la_minuta_y_a_los_pasos(monkeypatch):
    """Parte 7 · C6 (energía): «No lo sé ahora» en las tomas queda Por confirmar, sin dar el dato por bueno."""
    caso = next(c for c in CASES if c["name"].startswith("caso 1"))
    r = run_case(caso, monkeypatch)
    s = Session(json.loads(r.state))
    a = dict(s.A)
    a["P33"] = {"v": "PC", "label": "Por confirmar", "pc52": True}
    a.pop("P33a", None)
    a.pop("P33b", None)
    a.pop("P52a", None)  # los pasos se vuelven a generar con la respuesta nueva
    doc = build_document(a, s.state["ctx"])
    texto = json.dumps(doc, ensure_ascii=False)
    assert "Por confirmar" in texto
    assert "si hay tomas de energía cerca de los equipos" in texto  # Pasos del cliente: «Confirmar con ID»
    assert "Faltan tomas de energía" not in texto  # no se da por faltante
