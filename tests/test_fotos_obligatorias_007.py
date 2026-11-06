"""0.0.7 · fotos obligatorias: «Guardar como correcta» y «Subir después» (cualquier estado del local)."""
import json

import pytest

from app.chat.sim.engine import Session, StepError, new_state, place_desc
from app.chat.sim.service import SimChat, node_prompt
from app.chat.schemas import ChatAnswerRequest


def _answer_default(s: Session, n):
    d = n.get("def")
    if n["kind"] == "ev":
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


def _run(estado: str, on_mandatory) -> Session:
    s = Session(new_state({"technician": "T", "todayIso": "2026-11-06"}))
    for _ in range(500):
        n = s.current()
        if n is None or n["kind"] == "fin":
            break
        if n["id"] == "P08":
            s.answer(estado)
            continue
        if n.get("parent") and not n.get("optional"):
            on_mandatory(s, n)
            continue
        _answer_default(s, n)
    return s


@pytest.mark.parametrize("estado", ["EN_OPERACION", "EN_OBRA", "POR_INAUGURAR", "SISTEMA_ANTERIOR"])
def test_guardar_como_correcta_en_cualquier_estado(estado, monkeypatch):
    monkeypatch.setenv("VISION_MOCK", "1")
    forced = []

    def force(s, n):
        s._push({"t": "try", "id": n["id"], "val": {"r": "nc", "m": "subir", "like": "una pared"}})
        p = node_prompt(s, s.current())
        assert p["evidence"]["canForce"] and p["evidence"]["canLater"]
        assert "Guardar como correcta" in p["evidence"]["message"]
        r = s.upload(["eA=="], "forzar", "Local en obra" if estado == "EN_OBRA" else "")
        assert r["status"] == "OK" and s.A[n["id"]]["forzada"]
        forced.append(n["id"])

    s = _run(estado, force)
    assert s.current()["kind"] == "fin" and forced and not s.pending_later()


def test_forzar_solo_si_la_ia_observo(monkeypatch):
    monkeypatch.setenv("VISION_MOCK", "1")

    def check(s, n):
        with pytest.raises(StepError):
            s.upload(["eA=="], "forzar")
        s.upload(["eA=="], "subir")

    assert _run("EN_OPERACION", check).current()["kind"] == "fin"


def test_subir_despues_bloquea_la_minuta_hasta_subirlas(monkeypatch):
    monkeypatch.setenv("VISION_MOCK", "1")
    s = _run("EN_OPERACION", lambda s, n: s.answer("@LATER"))
    assert s.current()["kind"] == "fin"
    pend = s.pending_later()
    assert pend and all(i.startswith(("EV#", "EVQ#")) for i in pend)
    chat = SimChat()
    for i in pend:
        r = chat.answer(ChatAnswerRequest(evaluationId="1", state=json.dumps(s.state), photosBase64=["eA=="], nodeId=i))
        s = Session(json.loads(r.state))
        assert r.lastEvidence and r.lastEvidence["nodeId"] == i
    assert not s.pending_later()
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=json.dumps(s.state), answer=""))
    assert r.pendingMandatory == []


def test_subir_despues_solo_en_fotos_obligatorias_de_la_lista():
    s = Session(new_state({"technician": "T", "todayIso": "2026-11-06"}))
    with pytest.raises(StepError):
        s._answer_evidence({"id": "E1c", "kind": "ev", "read": "ipconfig"}, "@LATER")
    with pytest.raises(StepError):
        s._answer_evidence({"id": "EV#Salón 1", "kind": "ev", "read": "photo", "parent": "EV", "optional": True}, "@LATER")


def test_descripcion_del_lugar_para_la_ia():
    d = place_desc({"k": "Calientes", "t": "Lugar de preparación"}, "EN_OPERACION")
    assert "Calientes" in d and "preparación" in d and "en operación" in d
    assert "EN OBRA" in place_desc({"k": "Caja", "t": "Dónde irá la caja"}, "EN_OBRA")


def test_minuta_no_se_genera_con_fotos_pendientes(monkeypatch):
    from app.chat.router import MinutaDocumentRequest, minuta_document
    monkeypatch.setenv("VISION_MOCK", "1")
    s = _run("EN_OBRA", lambda s, n: s.answer("@LATER"))
    doc = minuta_document(MinutaDocumentRequest(state=json.dumps(s.state)))
    assert "Frontis del local" in doc["missingMandatory"] and "blocks" not in doc


def test_minuta_muestra_solo_la_nota(monkeypatch):
    from app.chat.router import MinutaDocumentRequest, minuta_document
    monkeypatch.setenv("VISION_MOCK", "1")

    def force(s, n):
        s._push({"t": "try", "id": n["id"], "val": {"r": "nc", "m": "subir"}})
        s.upload(["eA=="], "forzar", "aquí irá Calientes")

    s = _run("EN_OBRA", force)
    doc = minuta_document(MinutaDocumentRequest(state=json.dumps(s.state)))
    txt = json.dumps(doc, ensure_ascii=False, default=str)
    assert "Nota: aquí irá Calientes" in txt and "guardada por el técnico" not in txt.lower()


def test_pendiente_observada_se_puede_guardar_como_correcta(monkeypatch):
    from app.chat.sim import vision
    monkeypatch.setenv("VISION_MOCK", "1")
    s = _run("EN_OPERACION", lambda s, n: s.answer("@LATER"))
    pid = s.pending_later()[0]
    monkeypatch.delenv("VISION_MOCK")
    monkeypatch.setattr(vision, "analyze", lambda *a, **k: vision.VisionResult(corresponde=False, legible=True, queMuestra="una pared"))
    chat = SimChat()
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=json.dumps(s.state), photosBase64=["eA=="], nodeId=pid))
    assert r.validationError and "Guardar como correcta" in r.validationError
    item = next(p for p in r.pendingMandatory if p["nodeId"] == pid)
    assert item["canForce"] and item["lastTry"] == "nc"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, photosBase64=["eA=="], nodeId=pid, mode="forzar", nota="pared de Calientes"))
    assert pid not in [p["nodeId"] for p in r.pendingMandatory] and r.lastEvidence["nodeId"] == pid
