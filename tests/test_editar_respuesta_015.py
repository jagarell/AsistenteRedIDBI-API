"""Editar una respuesta anterior del Chat IA sin perder las demás, y rubro «Otro» con el flujo completo."""
import json

import pytest

from app.chat.schemas import ChatAnswerRequest, ChatEditRequest, ChatStartRequest
from app.chat.sim.engine import Session
from app.chat.sim.flow import build
from app.chat.sim.service import SimChat
from tests.test_sim_engine import CASES, run_case

RESTOBAR = next(c for c in CASES if c["name"].startswith("caso 1"))


@pytest.fixture
def terminado(monkeypatch):
    return run_case(RESTOBAR, monkeypatch)


def _en_curso(state: str, hasta: str) -> str:
    """Corta la evaluación terminada justo después de responder `hasta` (simula el chat en curso)."""
    st = json.loads(state)
    idx = next(i for i, e in enumerate(st["order"]) if e["id"] == hasta)
    st["order"] = st["order"][: idx + 1]
    st.pop("edit", None)
    return json.dumps(st, ensure_ascii=False)


def _ids(state: str):
    return {e["id"] for e in json.loads(state)["order"] if e["t"] == "ans"}


def test_editar_sin_dependencias_conserva_todo(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P15")
    antes = _ids(st)
    previo = Session(json.loads(st)).A["P12b"]["v"]
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P12b", mode="reopen"))
    assert r.node["nodeId"] == "P12b"
    assert r.node["editing"] is True
    assert r.node["currentValue"] == previo
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="SI" if previo == "NO" else "NO"))
    assert r.validationError is None
    assert _ids(r.state) == antes  # nada se borró
    assert r.notices[0]["id"] == "EDIT_OK" and "se mantienen" in r.notices[0]["text"]
    # sigue donde se había quedado, no vuelve a preguntar lo ya respondido
    assert r.node["nodeId"] not in antes


def test_editar_texto_trae_lo_escrito(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P15")
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P04", mode="reopen"))
    assert r.node["defaultValue"] == Session(json.loads(st)).A["P04"]["v"]


def test_cambiar_proveedor_resetea_el_plan_que_ya_no_existe(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P15")
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P13", mode="reopen"))
    assert r.node["currentValue"] == "MOVISTAR"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="CLARO"))
    s = Session(json.loads(r.state))
    assert s.A["P13"]["v"] == "CLARO"
    if "P15" not in s.A:  # el plan dependía del proveedor: se vuelve a preguntar y se avisa
        assert r.node["nodeId"] == "P15"
        assert "dependían" in r.notices[0]["text"]
    for k in ("P01", "P09", "P11e", "P12", "P14"):
        assert k in s.A, k


def test_editar_seleccion_multiple_trae_lo_elegido_y_solo_resetea_lo_dependiente(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P15")
    s0 = Session(json.loads(st))
    prep0 = s0.A["P11e"]["v"]
    assert "Barra 2" in prep0
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P11e", mode="reopen"))
    # lo que ya había marcado sigue marcado (no vuelve a lo sugerido)
    assert r.node["selected"] == prep0
    nuevo = [p for p in prep0 if p != "Barra 2"] + ["Makis"]
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=json.dumps(nuevo, ensure_ascii=False)))
    assert r.validationError is None
    s = Session(json.loads(r.state))
    assert s.A["P11e"]["v"] == nuevo
    # lo que no depende de las áreas se conserva
    for k in ("P01", "P08", "P09", "P11f", "P12", "P13", "P14", "P15"):
        assert k in s.A, k
    # lo de «Barra 2» desaparece; «Makis» queda por preguntar
    assert not any("Barra 2" in k for k in s.A)
    assert "EDIT_OK" in [n["id"] for n in r.notices]
    # «Makis» se puede escribir con Otro y vuelve a salir marcado si se edita de nuevo
    r2 = chat.edit(ChatEditRequest(evaluationId="1", state=r.state, nodeId="P11e", mode="reopen"))
    assert "Makis" in r2.node["selected"] and "Makis" in [o["value"] for o in r2.node["options"]]


def test_editar_estado_del_local_resetea_lo_que_cambia(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P19a")
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P08", mode="reopen"))
    assert r.node["currentValue"] == "EN_OPERACION"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="EN_OBRA"))
    s = Session(json.loads(r.state))
    assert s.A["P08"]["v"] == "EN_OBRA"
    assert "P19a" not in s.A  # en obra no hay speedtest
    # «Tipo de conexión» y la ficha del local no dependen del estado: se conservan
    for k in ("P01", "P09", "P11e", "P12", "P14"):
        assert k in s.A, k
    assert "EDIT_OK" in [n["id"] for n in r.notices]


def test_terminada_reopen_sigue_funcionando(terminado):
    chat = SimChat()
    r = chat.edit(ChatEditRequest(evaluationId="1", state=terminado.state, nodeId="P13", mode="reopen"))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="CLARO"))
    assert r.completed


def _start_hasta(chat, hasta_rubro="OTRO:Lavandería"):
    r = chat.start(ChatStartRequest(evaluationId="1", technicianName="Técnico de prueba", today="11/10/2026"))
    respuestas = {"P01": "Lavandería Sol S.A.C.", "P01b": "20601234567", "P01c": "Lavandería Sol", "P03": "Av. Sol 123",
                  "P04": "Ana, administradora", "P05": "987654321", "P05b": "ana@sol.com", "P06": "2026-10-11",
                  "P07": "Técnico de prueba", "P08": "EN_OPERACION", "P09": hasta_rubro}
    while r.node and r.node["nodeId"] in respuestas:
        r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=respuestas[r.node["nodeId"]]))
        assert r.validationError is None, r.validationError
    return r


def test_rubro_otro_flujo_completo_sin_autoseleccion():
    chat = SimChat()
    r = _start_hasta(chat)
    n = r.node
    assert n["nodeId"] == "P11e"          # antes iba a «solo referencia» (P11r)
    assert n["selected"] == []            # nada marcado de antemano
    assert n["noneLabel"]                 # puede no tener áreas
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=json.dumps(["Taller", "Cocina"])))
    assert r.node["nodeId"] == "P11f" and r.node["selected"] == []
    s = Session(json.loads(r.state))
    assert s.X.simple is False
    # se hacen las preguntas del rubro completo: comandas en caja, tomas de energía, mozos y WiFi por zona
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=json.dumps(["Mesa"])))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=json.dumps(["Salón 1"])))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="1"))
    vistos = []
    for _ in range(4):
        vistos.append(r.node["nodeId"])
        if r.node["nodeId"] == "P12e":
            r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="NO"))
        elif r.node["nodeId"] == "P12b":
            r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="NO"))
        else:
            break
    assert "P12e" in vistos and "P12b" in vistos
    assert r.node["nodeId"] == "P12x"    # otras impresoras (0.0.19 · C5)
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=json.dumps([])))
    assert r.validationError is None and r.node["nodeId"] == "P33"     # tomas de energía
    N, X = build(Session(json.loads(r.state)).A, json.loads(r.state)["ctx"])
    assert X.mozosQ is True


def test_rubro_otro_sin_areas_de_preparacion():
    chat = SimChat()
    r = _start_hasta(chat)
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="@NONE"))
    assert r.validationError is None
    assert r.node["nodeId"] == "P11f"


def test_mantener_un_numero_escrito_con_otro(terminado):
    chat = SimChat()
    st = _en_curso(terminado.state, "P15")
    r = chat.edit(ChatEditRequest(evaluationId="1", state=st, nodeId="P15", mode="reopen"))
    assert r.node["currentValue"] == "OTRO:600"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=r.node["currentValue"]))
    assert r.validationError is None
    assert Session(json.loads(r.state)).A["P15"]["v"] == 600


def test_agregar_un_area_no_borra_lo_que_viene_despues(terminado):
    """Agregar «Makis» crea preguntas nuevas (su impresora); lo ya respondido después (WiFi, fotos, resumen) se conserva."""
    chat = SimChat()
    s0 = Session(json.loads(terminado.state))
    antes = set(s0.A)
    r = chat.edit(ChatEditRequest(evaluationId="1", state=terminado.state, nodeId="P11e", mode="reopen"))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state,
                                      answer=json.dumps(s0.A["P11e"]["v"] + ["Makis"], ensure_ascii=False)))
    s = Session(json.loads(r.state))
    perdidas = antes - set(s.A)
    assert perdidas == set(), perdidas
    assert "Makis" in r.node["text"] or "Makis" in r.node["nodeId"]  # pregunta por lo nuevo
    assert r.notices[0]["text"].startswith("Respuesta actualizada. Tus demás respuestas se mantienen")
