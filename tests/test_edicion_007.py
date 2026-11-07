"""0.0.7 · Parte 6: actualizar cualquier dato de una minuta desde el Asistente IA (caso real AMAT ROOFTOP, 05/11/2026)."""
import json
from pathlib import Path

import pytest

from app.asistente.edicion import aplicar, leer
from app.asistente.plan import plan_cambios
from app.chat.sim.engine import Session, StepError, new_state
from app.chat.sim.minuta import build_document

AMAT = (Path(__file__).parent / "data" / "actualizar_amat_rooftop.txt").read_text(encoding="utf-8")
OV = {"P01": "Aun no lo tengo", "P01c": "AMAT ROOFTOP", "P08": "EN_OBRA", "P09": "RESTOBAR",
      "P11e": ["Calientes", "Fríos", "Barra", "Panaderia", "Makis"], "P11f": ["Recojo", "Mesa"],
      "P11g#Recojo": ["Caja"], "P11g#Mesa": ["Zona de Makis", "Barra Principal", "Zona Vip"], "P12": "1"}


def _minuta_amat(monkeypatch) -> Session:
    monkeypatch.setenv("VISION_MOCK", "1")
    s = Session(new_state({"technician": "Yomira Mora", "todayIso": "2026-11-05"}))
    for _ in range(600):
        n = s.current()
        if n is None or n["kind"] == "fin":
            break
        i, d = n["id"], n.get("def")
        if i in OV:
            v = OV[i]
            s.answer(json.dumps(v) if isinstance(v, list) else v)
        elif i.startswith("P28h#"):
            s.answer("SI" if i.endswith("Panaderia") else "NO")
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
    assert s.current()["kind"] == "fin"
    return s


def _kv(doc, label):
    for b in doc["blocks"]:
        if b["t"] == "kv":
            for r in b["rows"]:
                if r["label"] == label:
                    return r.get("value")
    return None


def _table(doc, title):
    for i, b in enumerate(doc["blocks"]):
        if b["t"] == "h3" and b["text"] == title:
            return next(x for x in doc["blocks"][i + 1:] if x["t"] == "table")


def test_plan_amat_todo_son_datos_de_la_minuta():
    r = plan_cambios(AMAT, [])
    assert not r["criterio"]
    kinds = [i["k"] for i in r["items"]]
    assert kinds and set(kinds) == {"doc"}, kinds  # nada queda como observación suelta
    ops = [i["v"]["op"] for i in r["items"]]
    for op in ("rename", "listRep", "set", "routerEnc", "prnWhere", "prn", "prnAdd", "eq", "tomas", "photoDel"):
        assert op in ops, op


def test_router_no_se_lee_de_otra_frase():
    """Antes: «quita la imagen del gabinete» hacía creer que el router estaba dentro de un mueble."""
    ops, _ = leer(AMAT)
    enc = next(o for o in ops if o["op"] == "routerEnc")
    assert enc["enc"] is None
    r = plan_cambios("Quita la imagen del gabinete. El router queda en la sala de data center.", [])
    assert not any(i["k"] == "router" and i.get("enc") == "MUEBLE" for i in r["items"])


def test_minuta_amat_actualizada(monkeypatch):
    s = _minuta_amat(monkeypatch)
    ops = [i["v"] for i in plan_cambios(AMAT, [])["items"]]
    doc = build_document(s.A, s.state["ctx"], {"doc": ops})
    assert _kv(doc, "Áreas de preparación") == "Calientes, Fríos, Barra, Panaderia Mesón / Panaderia Amat, Makis"
    assert _kv(doc, "Canales y zonas de atención") == "Recojo: Barra de Makis, Barra Principal · Mesa: Barra de Makis, Barra Principal, Zona Vip"
    assert _kv(doc, "Tipo de conexión") == "Internet Satelital por implementar"
    assert _kv(doc, "Proveedor") == "Starlink"
    assert _kv(doc, "Dónde irá el router") == "En la sala de data center cerca al área de caja"
    assert _kv(doc, "Equipo de Caja") == "PC conectada por cable de red (a implementar)"
    assert _kv(doc, "WiFi") == "Por implementar" and _kv(doc, "Cámaras en la red") == "Por implementar"
    assert _kv(doc, "Equipos sin tomas cerca").startswith("IMP. Caja: no tiene aún tomas de energía; IMP. Panaderia AMAT:")
    prn = {r["cells"][0]: r["cells"] for r in _table(doc, "Impresoras")["rows"]}
    assert "IMP. Panaderia" not in prn and "IMP. Panaderia Mesón" in prn
    assert prn["IMP. Calientes"][4] == "Tiene punto de red - Habilitado"
    assert prn["IMP. Caja"][4] == "No tiene punto de red - No habilitado"
    assert prn["IMP. Panaderia AMAT"] == ["IMP. Panaderia AMAT", "Amat por definir", "Sin dato", "Sin dato",
                                         "No tiene punto de red - No habilitado", "Por confirmar"]
    eqv = {r["cells"][0]: r["cells"][4] for r in _table(doc, "Equipos varios")["rows"]}
    assert eqv["PC Caja"] == "Por implementar" and any("witch" in k and v == "Por implementar" for k, v in eqv.items())
    rules = {r["rule"]: r for r in next(b for b in doc["blocks"] if b["t"] == "rules")["rows"]}
    assert rules["IMP. Calientes de red por cable"]["status"] == "Cumple"
    titles = [(b.get("heading", ""), c["title"]) for b in doc["blocks"] if b["t"] in ("grid", "block") for c in b["cells"]]
    assert not any(t == "Gabinete" for _, t in titles) and any(t == "Switch" for _, t in titles)
    pan = [t for h, t in titles if h.startswith("IMP. Panaderia Mesón")]
    assert pan and "Selftest (hoja de prueba)" not in pan
    assert "IMP. Panaderia " not in json.dumps(doc["blocks"], ensure_ascii=False).replace("IMP. Panaderia Mesón", "").replace("IMP. Panaderia AMAT", "")


def test_equipos_sin_tomas_no_acepta_textos_sueltos():
    s = Session(new_state({}))
    n = {"id": "P33a", "kind": "multi", "opts": ["Router", "IMP. Caja"], "min": 0}
    with pytest.raises(StepError):
        s._parse(n, json.dumps(["Si"]))
    assert s._parse(n, json.dumps(["IMP. Caja"]))["v"] == ["IMP. Caja"]


def test_frases_comunes():
    ops, _ = leer("Proveedor: Claro. Razón social: Inversiones Amat S.A.C. Tipo de conexión: fibra óptica")
    got = {(o.get("label"), o.get("value")) for o in ops if o["op"] == "set"}
    assert ("Proveedor", "Claro") in got and ("Razón social", "Inversiones Amat S.A.C") in got
    assert ("Tipo de conexión", "Fibra óptica") in got
