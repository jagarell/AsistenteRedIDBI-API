"""Punto de red por impresora (Parte 7 · C6): pregunta, puntaje, trabajo del cliente y «Por confirmar»."""
import json

import pytest

from app.chat.sim.engine import Session
from app.chat.sim.minuta import build_document
from app.chat.sim.rules import gen_pasos
from app.chat.sim.scoring import crit_infra
from app.chat.sim.util import Obj
from tests.test_sim_engine import CASES, RANDOM, run_case

ALEATORIO_1 = next(c for c in RANDOM if c["name"] == "aleatorio 1")
ALEATORIO_2 = next(c for c in RANDOM if c["name"] == "aleatorio 2")


def _puntos(s):
    return next(c for c in crit_infra(s.X, s.R, s.A) if c.k == "Puntos de red")


def test_la_pregunta_solo_sale_si_el_cable_no_va_directo_al_router(monkeypatch):
    s = Session(json.loads(run_case(ALEATORIO_1, monkeypatch).state))
    con_pregunta = [p for p in s.X.printers if p.ptoQ]
    assert con_pregunta and all(p.con == "RED" and p.via not in ("ROUTER", "WIFI") for p in con_pregunta)
    assert all(p.punto for p in con_pregunta)
    assert all(not p.punto for p in s.X.printers if not p.ptoQ)


def test_puntaje_habilitado_sin_jack_y_sin_cable(monkeypatch):
    s = Session(json.loads(run_case(ALEATORIO_1, monkeypatch).state))
    s.X.printers = [Obj(name="A", con="RED", via="SWITCH", ptoQ=True, punto="HAB"),
                    Obj(name="B", con="RED", via="SWITCH", ptoQ=True, punto="SINJACK"),
                    Obj(name="C", con="RED", via="SOCKET", ptoQ=True, punto="SINCABLE"),
                    Obj(name="D", con="RED", via="SWITCH", ptoQ=True, punto="PC")]
    s.X.eqCable, s.X.libres, s.X.cajasInfo = 1, 4, []
    c = _puntos(s)
    # eqCable=1 era la impresora del socket: ahora se mide por su punto; el de «Por confirmar» no cuenta
    assert (c.r, c.d) == (1.5 / 3, "1.5 de 3 equipos por cable con puerto libre o punto de red")


def test_trabajo_del_cliente_por_punto_con_problema(monkeypatch):
    s = Session(json.loads(run_case(ALEATORIO_1, monkeypatch).state))
    malas = [p for p in s.X.printers if p.punto in ("SINJACK", "SINCABLE", "AVERIADO")]
    assert malas
    trabajos = [i.trabajo for i in s.R.it if i.id == "IMP-PTO"]
    assert len(trabajos) == len(malas)
    for p in malas:
        assert any(t.endswith(f"para IMP. {p.name}") for t in trabajos)
    pasos = " ".join(x["t"] for x in gen_pasos(s.X, s.R, s.A) if x["p"] == "Cliente")
    assert "Implementar" in pasos and f"para IMP. {malas[0].name}" in pasos


def test_por_confirmar_pasa_a_confirmar_con_id_y_no_puntua(monkeypatch):
    s = Session(json.loads(run_case(ALEATORIO_2, monkeypatch).state))
    pc = [p for p in s.X.printers if p.punto == "PC"]
    assert pc
    pend = s.por_confirmar()
    assert all(f"el estado del punto de red de la impresora ({p.name})" in pend for p in pc)
    pasos = " ".join(x["t"] for x in gen_pasos(s.X, s.R, s.A))
    assert "Confirmar con ID" in pasos and f"el estado del punto de red de la impresora ({pc[0].name})" in pasos
    assert not [i for i in s.R.it if i.id == "IMP-PTO" and any(i.t.startswith(f"IMP. {p.name}:") for p in pc)]


def test_la_minuta_muestra_el_punto_en_la_tabla_de_impresoras(monkeypatch):
    s = Session(json.loads(run_case(ALEATORIO_1, monkeypatch).state))
    doc = build_document(s.A, s.state["ctx"], None)
    celdas = [c for b in doc["blocks"] if b.get("t") == "table" and "Conexión" in b.get("head", []) for r in b["rows"] for c in r["cells"]]
    assert any("punto de red:" in c for c in celdas)
