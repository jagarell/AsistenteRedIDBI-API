"""Parte 4 (0.0.7): salidas «Por confirmar», escribir en opciones, adjuntos y avance."""
import json

import pytest

from app.chat import adjunto
from app.chat.router import AdjuntoUsarRequest, usar_adjunto
from app.chat.sim.engine import Session, StepError, new_state
from app.chat.sim.rules import gen_pasos

CTX = {"technician": "Técnico", "today": "11/10/2026", "todayIso": "2026-10-11"}


def _hasta(s: Session, target: str, overrides=None):
    overrides = overrides or {}
    for _ in range(120):
        n = s.current()
        if n["id"] == target:
            return n
        d = overrides.get(n["id"], n.get("def"))
        s.answer("" if d is None else str(d))
    raise AssertionError(f"no llegó a {target}")


def test_ruc_no_lo_tengo_y_no_se():
    for txt in ("no sé", "No lo tengo ahora"):
        s = Session(new_state(dict(CTX)))
        _hasta(s, "P01b")
        s.answer(txt)
        assert s.A["P01b"]["label"] == "Por confirmar"
        assert s.current()["id"] == "P01c"
        assert any("Enviar el RUC" in p["t"] for p in gen_pasos(s.X, s.R, s.A))


def test_encargado_no_esta():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P04")
    s.answer("No está en el local")
    assert s.A["P04"]["label"] == "Por confirmar"


def test_escribir_opcion_y_error():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P08")
    s.answer("en operación")
    assert s.A["P08"]["v"] == "EN_OPERACION"
    n = _hasta(s, "P09")
    with pytest.raises(StepError):
        s.answer("cevichería")


def test_plan_500_y_no_lo_se_ahora():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P15")
    s.answer("500")
    assert s.A["P15"]["v"] == 500
    s2 = Session(new_state(dict(CTX)))
    _hasta(s2, "P15")
    s2.answer("NS52")
    assert s2.A["P15"]["label"] == "Por confirmar" and s2.X.plan is None


def test_adjunto_usar_responde_las_tres_y_queda_en_p03():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P01")
    campos = [{"nodeId": "P01", "valor": "Inversiones Sol S.A.C."}, {"nodeId": "P01b", "valor": "20601234567"},
              {"nodeId": "P01c", "valor": "Pollería Sol"}]
    r = usar_adjunto(AdjuntoUsarRequest(evaluationId="1", state=json.dumps(s.state), campos=campos))
    assert r.node["nodeId"] == "P03"
    assert set(r.attachedNodeIds) == {"P01", "P01b", "P01c"}


def test_adjunto_usar_ruc_invalido_no_se_responde():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P01")
    campos = [{"nodeId": "P01", "valor": "Inversiones Sol S.A.C."}, {"nodeId": "P01b", "valor": "123"}]
    r = usar_adjunto(AdjuntoUsarRequest(evaluationId="1", state=json.dumps(s.state), campos=campos))
    assert r.node["nodeId"] == "P01b"


def test_avance_en_pregunta_4_es_menor_a_15():
    s = Session(new_state(dict(CTX)))
    _hasta(s, "P04")
    assert s.percent() < 15


def test_a_prefill_plan_y_proveedor():
    assert adjunto.a_prefill({"nodeId": "P13", "valor": "Movistar"})["v"] == "MOVISTAR"
    assert adjunto.a_prefill({"nodeId": "P15", "valor": "500 Mbps"})["v"] == "500"
