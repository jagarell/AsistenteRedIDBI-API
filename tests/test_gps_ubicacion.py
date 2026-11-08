"""Ubicación GPS del local (docs/0.0.7/03-gps-direccion.md y 04-geocodificacion.md)."""
import json

import pytest

from app import geo_reverse
from app.chat.sim.engine import Session
from app.chat.sim.minuta import build_document
from tests.test_sim_engine import CASES, run_case

RESTOBAR = next(c for c in CASES if c["name"].startswith("caso 1"))


@pytest.fixture
def terminado(monkeypatch):
    return run_case(RESTOBAR, monkeypatch)


def _filas(doc):
    out = {}
    for b in doc["blocks"]:
        if b.get("t") == "kv":
            for r in b["rows"]:
                out[r["label"]] = r
    return out


def _doc(state, edits=None):
    s = Session(json.loads(state))
    return build_document(s.A, s.state["ctx"], edits)


def test_sin_gps_queda_pendiente_y_distrito_se_deriva(terminado):
    f = _filas(_doc(terminado.state, {"datos": {"dir": "Av. Grau 450, Chancay"}}))
    assert f["Distrito / Departamento"]["value"] == "Chancay / Lima"
    assert f["Ubicación GPS"].get("pending") is True


def test_con_gps_la_minuta_lleva_enlace_al_mapa(terminado):
    gps = {"lat": -12.11868, "lng": -77.03318, "acc": 9,
           "geo": {"direccion": "Av. Del Ejército 956, Miraflores", "distrito": "Miraflores", "departamento": "Lima",
                   "coincidencia": {"nombre": "El Chinito", "distancia_m": 19}}}
    f = _filas(_doc(terminado.state, {"datos": {"dir": "Av. Del Ejército 956, Miraflores"}, "gps": gps}))
    assert f["Distrito / Departamento"]["value"] == "Miraflores / Lima"
    g = f["Ubicación GPS"]
    assert g["href"] == "https://www.google.com/maps?q=-12.118680,-77.033180"
    assert "±9 m" in g["value"] and "coincide con «El Chinito»" in g["value"]


def test_reverse_chancay_y_coincidencia(monkeypatch):
    monkeypatch.setattr(geo_reverse, "_reverse", lambda lat, lng: {
        "name": "", "address": {"road": "Av. Grau", "house_number": "450", "town": "Chancay", "county": "Provincia de Huaral",
                                "state": "Departamento de Lima"}})
    monkeypatch.setattr(geo_reverse, "_cerca", lambda n, lat, lng: [
        {"name": "El Chinito", "lat": "-11.57131", "lon": "-77.27101"}, {"name": "Otra Cosa", "lat": "-11.5713", "lon": "-77.2710"}])
    r = geo_reverse.reverse(-11.5713, -77.271, 8, "El Chinito")
    assert (r["distrito"], r["provincia"], r["departamento"]) == ("Chancay", "Huaral", "Lima")
    assert r["direccion"] == "Av. Grau 450, Chancay"
    assert r["coincidencia"]["nombre"] == "El Chinito" and r["coincidencia"]["distancia_m"] < 100
    assert r["mapa_url"] == "https://www.google.com/maps?q=-11.571300,-77.271000"


def test_reverse_sin_resultado_devuelve_igual_el_enlace(monkeypatch):
    def falla(*a):
        raise RuntimeError("sin red")
    monkeypatch.setattr(geo_reverse, "_reverse", falla)
    monkeypatch.setattr(geo_reverse, "_cerca", lambda *a: [])
    r = geo_reverse.reverse(-12.0, -77.0, None, "Cualquiera")
    assert r["direccion"] is None and r["coincidencia"] is None and r["mapa_url"].startswith("https://www.google.com/maps")


def test_coincidencia_lejana_no_cuenta(monkeypatch):
    monkeypatch.setattr(geo_reverse, "_reverse", lambda *a: None)
    monkeypatch.setattr(geo_reverse, "_cerca", lambda n, lat, lng: [{"name": "El Chinito", "lat": "-11.5800", "lon": "-77.2800"}])
    assert geo_reverse.reverse(-11.5713, -77.271, 8, "El Chinito")["coincidencia"] is None
