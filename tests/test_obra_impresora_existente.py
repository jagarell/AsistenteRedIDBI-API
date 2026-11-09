"""Parte 7 · C3: en obra la impresora pasa a «Existente» si la foto o su descripción lo muestran; solo si no hay ninguna se pregunta."""
import copy

from app.chat.sim.flow import build
from tests.test_edicion_007 import _minuta_amat


def _ids(a, ctx):
    return [n["id"] for n in build(a, ctx)[0]]


def test_con_foto_no_se_pregunta_y_sin_foto_si(monkeypatch):
    s = _minuta_amat(monkeypatch)
    assert s.A["E5a#Panaderia"]["v"] == "OK" and "P28h#Panaderia" not in s.A
    assert s.A["E5a#Calientes"]["v"] == "SKIP" and s.A["P28h#Calientes"]["v"] == "NO"
    con = {p.name: p.con for p in s.X.printers}
    assert con["Calientes"] == "NO" and con["Panaderia"] != "NO"


def test_la_descripcion_cuenta_como_existente(monkeypatch):
    s = _minuta_amat(monkeypatch)
    a = copy.deepcopy(s.A)
    del a["P28h#Calientes"]
    assert "P28h#Calientes" in _ids(a, s.state["ctx"])
    a["E5a#Calientes"]["desc"] = "Ya está instalada junto a la cocina"
    ids = _ids(a, s.state["ctx"])
    assert "P28h#Calientes" not in ids and "E5b#Calientes" in ids


def test_la_foto_saltada_de_una_impresora_que_no_existe_no_queda_pendiente(monkeypatch):
    s = _minuta_amat(monkeypatch)
    evid = next((i for i in s.R.it if i.id == "EVID"), None)
    assert evid is None or "E5a · Calientes" not in evid.d


def test_descripcion_otro_local_no_cuenta_la_impresora(monkeypatch):
    s = _minuta_amat(monkeypatch)
    a = copy.deepcopy(s.A)
    a["E5a#Panaderia"]["desc"] = "Esta impresora es de otro local, solo salió en la foto"
    nodos, X = build(a, s.state["ctx"])[:2]
    assert "Panaderia" not in [p.name for p in X.printers]
    assert "E5b#Panaderia" not in [n["id"] for n in nodos]


def test_descripcion_aun_no_existe_es_por_implementar_sin_preguntar(monkeypatch):
    s = _minuta_amat(monkeypatch)
    a = copy.deepcopy(s.A)
    a["E5a#Panaderia"]["desc"] = "Todavía no hay impresora, irá en esa barra"
    nodos, X = build(a, s.state["ctx"])[:2]
    p = next(p for p in X.printers if p.name == "Panaderia")
    ids = [n["id"] for n in nodos]
    assert p.con == "NO" and "P28h#Panaderia" not in ids and "E5b#Panaderia" not in ids
