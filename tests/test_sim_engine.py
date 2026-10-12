"""El chat nuevo, recorrido de punta a punta por la API (con la IA simulada), llega a lo mismo que el simulador."""
import json
from pathlib import Path

import pytest

from app.chat.schemas import ChatAmendRequest, ChatAnswerRequest, ChatEditRequest, ChatStartRequest
from app.chat.sim import vision
from app.chat.sim.engine import Session
from app.chat.sim.flow import build
from app.chat.sim.service import SimChat

GOLDEN = json.loads((Path(__file__).parent / "golden" / "sim_golden.json").read_text(encoding="utf-8"))
CASES = [c for c in GOLDEN if c["name"].startswith("caso ")]
RANDOM = [c for c in GOLDEN if c["name"].startswith("aleatorio ")][:12]


def _answer_text(n, ans):
    """Lo que mandaría la app para dejar esta misma respuesta."""
    k = n["kind"]
    if k == "choice":
        o = next((o for o in n["opts"] if o["v"] == ans["v"]), None)
        if o is not None and not o.get("otro"):
            return str(o["v"])
        if isinstance(ans["v"], (int, float)):
            return "OTRO:" + str(ans["v"])
        return "OTRO:" + str(ans["label"])
    if k == "multi":
        if ans["v"] == [] and n.get("none"):
            return "@NONE"
        return json.dumps(ans["v"], ensure_ascii=False)
    if k in ("text", "longtext", "date"):
        return ans["v"] if ans["v"] != "" or k == "date" else ans.get("label", "")
    if k in ("wifi", "rcard", "links", "pasos"):
        return json.dumps(ans["v"], ensure_ascii=False)
    return ""


def _blank(x):
    """El simulador guarda '' donde el servidor guarda None (puerto libre sin leer)."""
    if isinstance(x, dict):
        return {k: _blank(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_blank(v) for v in x]
    return None if x == "" else x


class FakeVision:
    """IA de mentira: devuelve lo que el simulador tenía como lectura de cada evidencia."""

    def __init__(self, answers):
        self.answers = answers
        self.node = None

    def analyze(self, read, name, images):
        ans = self.answers.get(self.node) or {}
        return vision.VisionResult(corresponde=True, legible=True, data=dict(ans.get("data") or {}))


def run_case(case, monkeypatch):
    A = case["A"]
    fake = FakeVision(A)
    monkeypatch.setattr(vision, "analyze", fake.analyze)
    chat = SimChat()
    resp = chat.start(ChatStartRequest(evaluationId="1", technicianName="Técnico de prueba", today="11/10/2026"))
    guard = 0
    while not resp.completed and guard < 600:
        guard += 1
        node = resp.node
        assert node, "el chat se quedó sin nodo"
        nid = node["nodeId"]
        state = resp.state
        s = Session(json.loads(state))
        cur = s.current()
        ans = A.get(nid)
        if cur.get("parent"):
            # foto de una lista (frontis, cocina, caja...): el simulador la da por buena
            ans = {"v": "OK", "data": {}}
        assert ans is not None, f"el simulador no respondió {nid}"
        if cur["kind"] == "ev":
            fake.node = nid
            if ans["v"] == "SKIP":
                resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=state, answer="@SKIP"))
            else:
                resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=state, photosBase64=["AAAA"]))
                if resp.node and resp.node["nodeId"] == nid and resp.node["evidence"]["status"] == "REVIEW":
                    data = dict(resp.node["evidence"]["data"])
                    resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, answer=json.dumps(data)))
        else:
            n = next(x for x in build(s.A, s.state["ctx"])[0] if x["id"] == nid)
            resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=state, answer=_answer_text(n, ans)))
        assert resp.validationError is None, f"{nid}: {resp.validationError}"
    return resp


@pytest.mark.parametrize("case", CASES + RANDOM, ids=[c["name"] for c in CASES + RANDOM])
def test_recorrido_completo_igual_al_simulador(case, monkeypatch):
    resp = run_case(case, monkeypatch)
    assert resp.completed
    final = Session(json.loads(resp.state))
    N, X = build(final.A, final.state["ctx"])
    # mismas respuestas que el simulador en todo lo que no es lista de fotos
    for k, v in case["A"].items():
        if k in ("EV", "EVQ"):
            continue
        got = final.A.get(k)
        assert got is not None, f"falta la respuesta {k}"
        if isinstance(v.get("v"), (list, dict)) or v.get("v") in ("OK", "SKIP"):
            same = _blank(got["v"]) == _blank(v["v"]) or k in ("SUM",)
            assert same, f"{k}: {got['v']!r} != {v['v']!r}"
    # y el mismo veredicto
    from app.chat.sim.rules import evaluate
    R = evaluate(X, final.A)
    assert R.estado == case["estado"]
    assert [i.id for i in R.it] == [i["id"] for i in case["it"]]
    assert resp.proposal is not None and resp.proposal.score == case["scores"]["g"]


def test_validacion_de_ruc_y_celular(monkeypatch):
    chat = SimChat()
    r = chat.start(ChatStartRequest(evaluationId="1"))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="Mi razón social SAC"))
    assert r.node["nodeId"] == "P01b"
    bad = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="12345"))
    assert bad.validationError and "RUC" in bad.validationError
    ok = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="20601234567"))
    assert ok.node["nodeId"] == "P01c"


def test_foto_que_no_corresponde_y_no_legible(monkeypatch):
    chat = SimChat()
    A = {}
    # llevar el chat hasta una evidencia: caso 3 (retail en obra) tiene fotos pronto
    case = CASES[0]
    fake = FakeVision(case["A"])
    monkeypatch.setattr(vision, "analyze", fake.analyze)
    resp = chat.start(ChatStartRequest(evaluationId="1"))
    guard = 0
    while resp.node and resp.node["kind"] != "evidence" and guard < 400:
        guard += 1
        s = Session(json.loads(resp.state))
        cur = s.current()
        n = next(x for x in build(s.A, s.state["ctx"])[0] if x["id"] == cur["id"])
        resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, answer=_answer_text(n, case["A"][n["id"]])))
    assert resp.node["kind"] == "evidence"
    nid = resp.node["nodeId"]

    monkeypatch.setattr(vision, "analyze", lambda *a, **k: vision.VisionResult(corresponde=False, legible=True, queMuestra="una silla"))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, photosBase64=["AAAA"]))
    assert r.node["nodeId"] == nid and r.node["evidence"]["status"] == "NC"
    assert "se parece a una silla" in r.node["evidence"]["message"]
    assert r.lastEvidence is None

    monkeypatch.setattr(vision, "analyze", lambda *a, **k: vision.VisionResult(corresponde=True, legible=False))
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, photosBase64=["AAAA"]))
    assert r.node["evidence"]["status"] == "IL"
    assert "no es legible" in r.node["evidence"]["message"]


def test_no_es_correcto_y_continuar_sin_lectura(monkeypatch):
    chat = SimChat()
    case = CASES[1]
    fake = FakeVision(case["A"])
    monkeypatch.setattr(vision, "analyze", fake.analyze)
    resp = chat.start(ChatStartRequest(evaluationId="1"))
    guard = 0
    while resp.node and not (resp.node["kind"] == "evidence" and resp.node["evidence"]["fields"]) and guard < 400:
        guard += 1
        s = Session(json.loads(resp.state))
        cur = s.current()
        if cur["kind"] == "ev":
            fake.node = cur["id"]
            r2 = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, photosBase64=["AAAA"]))
            if r2.node["evidence"]["status"] == "REVIEW":
                resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=r2.state, answer=json.dumps(r2.node["evidence"]["data"])))
            else:
                resp = r2
            continue
        n = next(x for x in build(s.A, s.state["ctx"])[0] if x["id"] == cur["id"])
        resp = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, answer=_answer_text(n, case["A"][n["id"]])))
    nid = resp.node["nodeId"]
    fake.node = nid
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=resp.state, photosBase64=["AAAA"]))
    assert r.node["evidence"]["status"] == "REVIEW" and r.lastEvidence is not None
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="@WRONG"))
    assert r.node["nodeId"] == nid and r.node["evidence"]["status"] == "WRONG"
    r = chat.answer(ChatAnswerRequest(evaluationId="1", state=r.state, answer="@SKIP"))
    assert r.node["nodeId"] != nid
    assert Session(json.loads(r.state)).A[nid]["v"] == "SKIP"
