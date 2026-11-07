"""0.0.15: equipo de los mozos (tablet, celular, iMin móvil, otro o por confirmar) y descripción de cada evidencia."""
import json

import pytest

from app.chat.schemas import ChatAnswerRequest, ChatEditRequest, ChatEvidenceNoteRequest
from app.chat.sim import vision
from app.chat.sim.engine import Session
from app.chat.sim.minuta import build_document
from app.chat.sim.rules import evaluate
from app.chat.sim.service import SimChat
from tests.test_sim_engine import CASES, run_case

RESTOBAR = next(c for c in CASES if c["name"].startswith("caso 1"))


@pytest.fixture
def terminado(monkeypatch):
    return run_case(RESTOBAR, monkeypatch)


def _doc(state: str) -> str:
    s = Session(json.loads(state))
    return json.dumps(build_document(s.A, s.state["ctx"]), ensure_ascii=False)


def _mozos(chat, state, respuesta):
    r = chat.edit(ChatEditRequest(evaluationId="1", state=state, nodeId="P09c", mode="reopen"))
    assert r.node["nodeId"] == "P09c"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer=respuesta))
    assert r.validationError is None, r.validationError
    return r, Session(json.loads(r.state))


def test_mozos_opciones(terminado):
    chat = SimChat()
    r = chat.edit(ChatEditRequest(evaluationId="1", state=terminado.state, nodeId="P09c", mode="reopen"))
    vals = [o["value"] for o in r.node["options"]]
    labels = [o["label"] for o in r.node["options"]]
    assert vals[:4] == ["TABLET", "CELULAR", "IMIN_MOVIL", "NO"]
    assert "Otro (escribir)" in labels and "Aún por confirmar (sugerir iMin móvil)" in labels
    assert r.node["currentValue"] == "TABLET"


def test_mozos_por_confirmar_sugiere_imin_movil(terminado):
    r, s = _mozos(SimChat(), terminado.state, "NS52")
    assert s.A["P09c"]["pc52"] is True
    R = evaluate(s.X, s.A)
    rec = next(i for i in R.it if i.id == "R_IMIN_MOVIL")
    assert "Sugerir iMin móvil" in rec.d
    assert s.X.wifiSkip is False  # se revisa el WiFi por zona por si acaso
    assert "Mozos toman pedidos con" in _doc(r.state)


def test_mozos_con_imin_movil_y_otro_escrito(terminado):
    chat = SimChat()
    r, s = _mozos(chat, terminado.state, "IMIN_MOVIL")
    assert any(i.id == "R_IMIN_MOVIL" for i in evaluate(s.X, s.A).it)
    r, s = _mozos(chat, terminado.state, "OTRO:PDA Sunmi de mano")
    assert s.A["P09c"] == {"v": "OTRO", "label": "PDA Sunmi de mano"}
    assert s.X.wifiSkip is False
    r, s = _mozos(chat, terminado.state, "NO")
    assert s.X.wifiSkip is True
    assert not any(i.id == "R_IMIN_MOVIL" for i in evaluate(s.X, s.A).it)


def _foto_id(state: str) -> str:
    s = Session(json.loads(state))
    return next(k for k in s.A if k.startswith("EV#Frontis"))


def test_descripcion_agregar_editar_borrar(terminado):
    chat = SimChat()
    fid = _foto_id(terminado.state)
    r = chat.evidence_note(ChatEvidenceNoteRequest(evaluationId="1", state=terminado.state, nodeId=fid,
                                                   descripcion="Frontis con letrero nuevo; la puerta da a la calle."))
    assert r.validationError is None
    assert r.evidenceNotes[fid] == "Frontis con letrero nuevo; la puerta da a la calle."
    assert "Descripción: Frontis con letrero nuevo" in _doc(r.state)
    r = chat.evidence_note(ChatEvidenceNoteRequest(evaluationId="1", state=r.state, nodeId=fid, descripcion="Frontis del local"))
    assert r.evidenceNotes[fid] == "Frontis del local"
    assert "Descripción: Frontis del local" in _doc(r.state) and "letrero nuevo" not in _doc(r.state)
    r = chat.evidence_note(ChatEvidenceNoteRequest(evaluationId="1", state=r.state, nodeId=fid, descripcion=""))
    assert fid not in r.evidenceNotes
    assert "Descripción:" not in _doc(r.state)
    assert r.completed  # la evaluación sigue terminada


def test_descripcion_solo_en_evidencias(terminado):
    r = SimChat().evidence_note(ChatEvidenceNoteRequest(evaluationId="1", state=terminado.state, nodeId="P13", descripcion="x"))
    assert r.validationError


def test_cambiar_foto_conserva_descripcion_y_la_ia_la_recibe(terminado, monkeypatch):
    chat = SimChat()
    vistos = []

    def fake(read, name, images):
        vistos.append(name)
        return vision.VisionResult(corresponde=True, legible=True, data={})

    monkeypatch.setattr(vision, "analyze", fake)
    fid = _foto_id(terminado.state)
    r = chat.evidence_note(ChatEvidenceNoteRequest(evaluationId="1", state=terminado.state, nodeId=fid, descripcion="Frontis de noche"))
    # «Cambiar foto»: se vuelve a pedir solo esa foto y se sube otra; las demás respuestas se conservan
    antes = {e["id"] for e in json.loads(r.state)["order"] if e["t"] == "ans"}
    r = chat.edit(ChatEditRequest(evaluationId="1", state=r.state, nodeId=fid, mode="reopen"))
    assert r.node["nodeId"] == fid
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, photosBase64=["AAAA"]))
    assert r.validationError is None
    assert r.evidenceNotes[fid] == "Frontis de noche"
    assert "Frontis de noche" in vistos[-1]
    despues = {e["id"] for e in json.loads(r.state)["order"] if e["t"] == "ans"}
    assert despues == antes


def test_descripcion_al_subir(terminado, monkeypatch):
    chat = SimChat()
    monkeypatch.setattr(vision, "analyze", lambda read, name, images: vision.VisionResult(corresponde=True, legible=True, data={}))
    fid = _foto_id(terminado.state)
    r = chat.edit(ChatEditRequest(evaluationId="1", state=terminado.state, nodeId=fid, mode="reopen"))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, photosBase64=["AAAA"], descripcion="Ya tiene el letrero"))
    assert r.evidenceNotes[fid] == "Ya tiene el letrero"
    assert "Descripción: Ya tiene el letrero" in _doc(r.state)


def test_asistente_pedir_reporte_no_abre_nueva_minuta():
    """«Hazme un reporte de los técnicos que están por terminar su minuta» pedía datos, no redactar una minuta."""
    from app.asistente.router import MensajeRequest, asistente_mensaje
    for t in ("Hazme un reporte de todos los técnicos que están por terminar su minuta", "Reportes",
              "Genera un informe de las minutas por validar"):
        r = asistente_mensaje(MensajeRequest(texto=t, rol="adm", contexto={}))
        assert r["tipo"] != "tipo_minuta", t
    assert asistente_mensaje(MensajeRequest(texto="Redacta una minuta nueva", rol="tec", contexto={}))["tipo"] == "tipo_minuta"
