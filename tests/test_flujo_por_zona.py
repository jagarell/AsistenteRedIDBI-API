"""0.0.20 · el chat se hace por zona: la impresora de cada caja se pregunta justo después del equipo de esa caja."""
import json

from app.chat.sim.engine import Session, new_state
from tests.test_edicion_007 import OV


def _recorrido(monkeypatch, cajas: str):
    """Responde todo con los valores por defecto y devuelve los ids de las preguntas en el orden en que se hicieron."""
    monkeypatch.setenv("VISION_MOCK", "1")
    ov = {**OV, "P12": cajas}
    s = Session(new_state({"technician": "Yomira Mora", "todayIso": "2026-11-05"}))
    orden = []
    for _ in range(800):
        n = s.current()
        if n is None or n["kind"] == "fin":
            break
        i, d = n["id"], n.get("def")
        orden.append(i)
        if i in ov:
            v = ov[i]
            s.answer(json.dumps(v) if isinstance(v, list) else v)
        elif i.startswith("E5a#"):
            s.answer("@SKIP")
        elif i.startswith("P28h#"):
            s.answer("SI")
        elif i == "EVO":
            s.answer(json.dumps(["Gabinete", "Switch"]))
        elif n["kind"] == "ev":
            if n.get("parent") or i.startswith(("E5", "EVQ")):
                s.upload(["eA=="], "subir")
                if s.state.get("pending"):
                    s.answer(json.dumps(s.state["pending"]["data"]))
            else:
                s.answer("@SKIP")
        elif n["kind"] == "multi":
            s.answer(json.dumps(d or n.get("sel") or n["opts"][:1]))
        elif n["kind"] in ("links", "pasos", "rcard"):
            s.answer(json.dumps(d if d is not None else []))
        elif n["kind"] == "wifi":
            s.answer(json.dumps(d if d is not None else {}))
        elif n["kind"] == "summary":
            s.answer("OK")
        elif n["kind"] == "choice":
            s.answer(str(d if d is not None else n["opts"][0]["v"]))
        else:
            s.answer(str(d if d is not None else ""))
    return orden


def test_cada_caja_va_con_su_impresora_antes_de_pasar_a_la_siguiente(monkeypatch):
    orden = _recorrido(monkeypatch, "2")
    pos = {i: orden.index(i) for i in ("P22#1", "E5a#Caja 1", "P22#2", "E5a#Caja 2")}
    assert pos["P22#1"] < pos["E5a#Caja 1"] < pos["P22#2"] < pos["E5a#Caja 2"]


def test_las_impresoras_de_preparacion_van_despues_de_todas_las_cajas(monkeypatch):
    orden = _recorrido(monkeypatch, "2")
    ultima_caja = orden.index("E5a#Caja 2")
    preparacion = [i for i in orden if i.startswith("E5a#") and i not in ("E5a#Caja 1", "E5a#Caja 2")]
    assert preparacion, "el caso de prueba tiene impresoras de preparación"
    assert all(orden.index(i) > ultima_caja for i in preparacion)


def test_con_una_sola_caja_su_impresora_sigue_al_equipo(monkeypatch):
    orden = _recorrido(monkeypatch, "1")
    assert orden.index("P22#1") < orden.index("E5a#Caja")
