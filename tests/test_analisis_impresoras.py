"""Análisis IA › Equipamiento: «Impresora adecuada» y «Estado de las impresoras» se reparten entre todas las impresoras."""
import json

from app.chat.sim.engine import Session
from app.chat.sim.scoring import crit_equip
from app.chat.sim.util import Obj
from tests.test_sim_engine import CASES, run_case


def test_las_impresoras_por_implementar_cuentan_en_el_denominador(monkeypatch):
    caso = next(c for c in CASES if c["name"].startswith("caso 1"))
    s = Session(json.loads(run_case(caso, monkeypatch).state))
    base = {c.k: c for c in crit_equip(s.X, s.R, s.A)}
    n0 = len(s.X.printers)
    existentes = [p for p in s.X.printers if p.con and p.con not in ("NO", "NONE")]
    assert existentes, "el caso debe tener impresoras existentes"
    # seis impresoras más que aún no existen (por implementar): el puntaje se reparte entre todas
    for i in range(6):
        s.X.printers.append(Obj(name=f"Nueva{i}", con="NO", prep=False, estado=None))
    c = {x.k: x for x in crit_equip(s.X, s.R, s.A)}
    n = n0 + 6
    assert abs(c["Impresora adecuada"].r - base["Impresora adecuada"].r * n0 / n) < 1e-9
    assert f"de {n} impresoras del tipo correcto" in c["Impresora adecuada"].d
    assert "6 por implementar" in c["Impresora adecuada"].d
    assert abs(c["Estado de las impresoras"].r - base["Estado de las impresoras"].r * n0 / n) < 1e-9
    assert c["Estado de las impresoras"].d.count("por implementar") == 6
