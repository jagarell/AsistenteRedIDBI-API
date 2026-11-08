"""Análisis IA: «Conexión por cable» cuenta todos los equipos y «Segmento de red» exige evidencia de red."""
import json

from app.chat.sim.engine import Session
from app.chat.sim.scoring import crit_infra
from tests.test_sim_engine import CASES, run_case


def _crit(nombre_caso, monkeypatch):
    caso = next(c for c in CASES if c["name"].startswith(nombre_caso))
    s = Session(json.loads(run_case(caso, monkeypatch).state))
    return s, {c.k: c for c in crit_infra(s.X, s.R, s.A)}


def test_sin_evidencia_de_red_el_segmento_es_na(monkeypatch):
    s, c = _crit("caso 2", monkeypatch)  # pollería sin internet: no hay speedtest, ipconfig ni escáner
    assert not (s.X.ipconfig or s.X.scanner or s.R.sp)
    assert c["Segmento de red"].r is None
    assert "sin evidencia" in c["Segmento de red"].d


def test_con_evidencia_el_segmento_se_calcula(monkeypatch):
    s, c = _crit("caso 1", monkeypatch)
    assert (s.X.ipconfig or s.X.scanner or s.R.sp)
    assert c["Segmento de red"].d != "sin evidencia de red (ipconfig, speedtest o escáner de IP)"


def test_conexion_por_cable_cuenta_todas_las_impresoras(monkeypatch):
    s, c = _crit("caso 1", monkeypatch)
    conectadas = [p for p in s.X.printers if p.con and p.con not in ("NO", "NONE")]
    cajas = [x for x in s.X.cajasInfo if (x.eq == "SI" and x.sysImp is not False)] + [x for x in s.X.cajasInfo if x.rasp]
    esperado = len(conectadas) + len(cajas)
    assert f"de {esperado} equipos" in c["Conexión por cable"].d
