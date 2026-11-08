"""Análisis IA: AnyDesk y calidad WiFi se reparten entre todo lo registrado; lo no medido no suma."""
import json

from app.chat.sim.engine import Session
from app.chat.sim.scoring import crit_equip, crit_wifi
from app.chat.sim.util import Obj
from tests.test_sim_engine import CASES, run_case


def test_calidad_wifi_parcial_se_reparte_entre_todas_las_zonas():
    X = Obj(wifiSkip=False, allZ=["Salón", "Cocina", "Barra", "Terraza"], sinSenal=[], solWifi=None,
            wz=[Obj({"z": "Salón", "cal": "Excelente"}), Obj({"z": "Cocina", "cal": "Buena"})])
    c = {x.k: x for x in crit_wifi(X, Obj())}
    assert abs(c["Calidad medida"].r - (1 + 0.85) / 4) < 1e-9
    assert "2 de 4 zonas medidas" in c["Calidad medida"].d


def test_calidad_wifi_sin_medicion_es_na():
    X = Obj(wifiSkip=False, allZ=["Salón", "Cocina"], sinSenal=[], solWifi=None, wz=[])
    assert {x.k: x for x in crit_wifi(X, Obj())}["Calidad medida"].r is None


def test_anydesk_se_reparte_entre_todas_las_cajas(monkeypatch):
    caso = next(c for c in CASES if c["name"].startswith("caso 3"))  # supermercado de 2 cajas
    s = Session(json.loads(run_case(caso, monkeypatch).state))
    cj = s.X.cajasInfo
    assert len(cj) == 2
    for c in cj:
        c.anydesk = {"codigo": "123"}
    s.A["E7#1"] = {"v": "OK"}  # solo una caja mostró su AnyDesk
    s.A.pop("E7#2", None)
    c = {x.k: x for x in crit_equip(s.X, s.R, s.A)}["Acceso remoto (AnyDesk)"]
    assert c.r == 0.5 and "1 de 2 equipos de caja" in c.d
