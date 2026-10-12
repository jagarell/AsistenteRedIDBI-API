"""Capa HTTP del chat nuevo: arma las respuestas (`ChatResponse`) a partir de la sesión del simulador."""
import json
from datetime import date
from typing import Any, Dict, List, Optional

from app.chat.schemas import (
    ChatAmendRequest, ChatAnswerRequest, ChatEditRequest, ChatProposal, ChatResponse, ChatStartRequest, EquipmentRecommendation, InputType,
)
from app.chat.sim.engine import BLOCK_KEYS, BLOCKS, RC_FIELDS, Session, StepError, new_state
from app.chat.sim.flow import fmt_date
from app.chat.sim.reading import field_specs, read_label
from app.chat.sim.scoring import resumen_ia
from app.chat.sim.util import fmt

STATE_KEY = "__state"
ERR = {
    "il": "La evidencia no es legible. Vuelve a tomar la foto o salta la evidencia.",
    "wrong": "Indicaste que la lectura no es correcta. Vuelve a tomar o subir la foto, o continúa sin esta lectura (queda pendiente en la minuta).",
}
_INPUT = {"text": InputType.TEXT, "date": InputType.TEXT, "longtext": InputType.TEXT, "choice": InputType.CHOICE,
          "multi": InputType.MULTI_SELECT, "ev": InputType.EVIDENCE, "rcard": InputType.READ_CARD, "links": InputType.LINKS,
          "pasos": InputType.STEPS, "wifi": InputType.WIFI_MEASURE, "summary": InputType.SUMMARY}


def _iso_today(request: ChatStartRequest) -> str:
    today = request.today or date.today().strftime("%d/%m/%Y")
    m = __import__("re").fullmatch(r"(\d{2})/(\d{2})/(\d{4})", today)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else date.today().isoformat()


def err_message(read: str, name: str, last: Optional[Dict[str, Any]], mandatory: bool) -> Optional[str]:
    if not last:
        return None
    r = last["r"]
    if r == "il":
        return "La evidencia no es legible. Vuelve a tomar la foto." if mandatory else ERR["il"]
    if r == "wrong":
        return ERR["wrong"]
    if r == "nc":
        like = last.get("like") or "otra cosa"
        tail = "Vuelve a subir la foto." if mandatory else "Vuelve a tomar o subir la foto, o salta la evidencia."
        return f"La imagen no corresponde a lo solicitado ({name or 'la evidencia'}): se parece a {like}. {tail}"
    return None


def _router_defaults(s: Session) -> Dict[str, Any]:
    """Cuadro del router: junta lo que leyó la IA en las 3 fotos y el ipconfig."""
    a = s.A
    ports = (a.get("E2") or {}).get("data") or {}
    label = (a.get("E2e") or {}).get("data") or {}
    gw = ((a.get("E1c") or {}).get("data") or {}).get("gw")
    libres, total, ocup = ports.get("libres"), ports.get("puertos"), ports.get("ocupados")
    return {"ip": gw or "", "proveedor": s.X.proveedor or "", "marca": label.get("marca") or "", "modelo": label.get("modelo") or "",
            "sn": label.get("sn") or "", "puertos": total, "libres": libres, "ocupados": ocup}


def node_prompt(s: Session, n: Dict[str, Any]) -> Dict[str, Any]:
    kind = n["kind"]
    b = n.get("b") or ""
    prompt: Dict[str, Any] = {
        "nodeId": n["id"], "scope": "", "kind": "question", "inputType": (_INPUT.get(kind) or InputType.TEXT).value,
        "text": n.get("text", ""), "required": True,
        "block": b, "blockLabel": BLOCKS.get(b, ""), "blockIndex": BLOCK_KEYS.index(b) + 1 if b in BLOCK_KEYS else 0,
        "blockCount": len(BLOCK_KEYS),
    }
    if kind == "text":
        prompt["suggestions"] = list(n.get("sug") or [])
        prompt["hint"] = n.get("ph") or ""
        prompt["keyboard"] = "phone" if n["id"] == "P05" else "number" if n.get("num") else "text"
        if n["id"] == "P07":
            prompt["defaultValue"] = s.state["ctx"].get("technician") or ""
    elif kind == "longtext":
        prompt["hint"] = n.get("ph") or ""
        prompt["multiline"] = True
    elif kind == "date":
        prompt["keyboard"] = "date"
        prompt["required"] = bool(n.get("req"))
        if n["id"] == "P06":
            prompt["defaultValue"] = s.state["ctx"].get("todayIso") or ""
    elif kind == "choice":
        prompt["options"] = [{"value": str(o["v"]), "label": o["l"], "other": bool(o.get("otro")), "numeric": bool(o.get("num"))} for o in n["opts"]]
        if n.get("unit"):
            prompt["unit"] = n["unit"]
    elif kind == "multi":
        prompt["options"] = [{"value": o, "label": o} for o in n["opts"]]
        prompt["selected"] = list(n.get("sel") or [])
        prompt["noneLabel"] = n.get("none")
        prompt["minSelected"] = n.get("min") or 0
        prompt["allowOther"] = True
    elif kind == "rcard":
        prompt["fields"] = [{"key": f[0], "label": f[1], "type": f[2] if len(f) > 2 else "text"} for f in RC_FIELDS]
        prompt["value"] = _router_defaults(s)
    elif kind == "links":
        prompt["required"] = False
        prompt["hint"] = "Drive, OneDrive, YouTube u otro"
        prompt["videoTypes"] = __import__("app.chat.sim.flow", fromlist=["CAT"]).CAT["VID_TIPOS"]
    elif kind == "pasos":
        from app.chat.sim.rules import gen_pasos
        prompt["value"] = gen_pasos(s.X, s.R, s.A)
    elif kind == "wifi":
        prompt["zones"] = list(n["zones"])
    elif kind == "summary":
        prompt["kind"] = "summary"
    elif kind == "ev":
        base = n["id"].split("#")[0]
        prompt["kind"] = "evidence"
        prompt["evidenceCode"] = base
        prompt["scope"] = n["id"].split("#", 1)[1] if "#" in n["id"] else ""
        mandatory = not s.evidence_skippable(n)
        prompt["skippable"] = not mandatory
        prompt["maxFiles"] = 3
        pending = s.state.get("pending")
        tries = s.TRIES.get(n["id"]) or []
        last = tries[-1] if tries and isinstance(tries[-1], dict) else (None if not tries else {"r": tries[-1]})
        status = "WAITING"
        ev: Dict[str, Any] = {"read": n["read"], "name": n.get("name") or "", "fields": field_specs(n["read"]) if n["read"] != "photo" else []}
        if pending and pending.get("id") == n["id"]:
            status = "REVIEW"
            data = dict(pending["data"])
            ev["data"] = data
            ev["label"] = read_label(n["read"], data)
            ev["unavailable"] = bool(pending.get("unavailable"))
            ev["mode"] = pending.get("m", "subir")
            if pending.get("unavailable"):
                ev["message"] = "La lectura automática no está disponible ahora. Escribe los datos que ves en la foto."
        elif last:
            status = {"il": "IL", "nc": "NC", "wrong": "WRONG"}.get(last["r"], "WAITING")
            ev["message"] = err_message(n["read"], n.get("name") or "", last, mandatory)
        ev["status"] = status
        ev["lastTry"] = last["r"] if last else None
        prompt["evidence"] = ev
        if n.get("item") and n["item"].get("opt"):
            prompt["optional"] = True
    return prompt


class SimChat:
    """Operaciones del chat: start, answer (con o sin fotos), amend y edit."""

    # ---- entradas -------------------------------------------------------------
    def start(self, request: ChatStartRequest) -> ChatResponse:
        ctx = {"technician": request.technicianName or "", "today": request.today or date.today().strftime("%d/%m/%Y"),
               "todayIso": _iso_today(request)}
        return self._respond(request.evaluationId, Session(new_state(ctx)))

    def answer(self, request: ChatAnswerRequest) -> ChatResponse:
        s = Session(json.loads(request.state))
        before = s.current()
        answered_id = before["id"] if before else None
        last_evidence: Optional[Dict[str, Any]] = None
        processed: Optional[List[str]] = None
        cross: List[str] = []
        try:
            if before is not None and before["kind"] == "ev" and request.photosBase64:
                info = s.upload(request.photosBase64[:3], request.mode or "subir")
                processed = info.get("processedImages")
                if info["status"] in ("OK", "REVIEW"):
                    last_evidence = self._evidence_info(before, info)
                return self._respond(request.evaluationId, s, last_evidence=last_evidence, processed=processed, answered_id=None)
            s.answer(request.answer)
        except StepError as exc:
            return self._respond(request.evaluationId, s, validation_error=str(exc), answered_id=None)
        evidence = None
        if before is not None and before["kind"] == "ev" and (s.A.get(before["id"]) or {}).get("v") == "OK":
            evidence = self._evidence_info(before, {"count": s.A[before["id"]].get("count") or 1,
                                                    "extracted": s.A[before["id"]].get("data") or {}}, confirmed=True)
        return self._respond(request.evaluationId, s, last_evidence=evidence, answered_id=answered_id)

    def amend(self, request: ChatAmendRequest) -> ChatResponse:
        s = Session(json.loads(request.state))
        try:
            node_id = request.nodeId or (f"{request.evidenceCode}#{request.evidenceScope}" if request.evidenceScope else request.evidenceCode)
            s.amend_reading(node_id, request.fields, request.deleted, request.restore)
        except StepError as exc:
            return self._respond(request.evaluationId, s, validation_error=str(exc))
        return self._respond(request.evaluationId, s)

    def edit(self, request: ChatEditRequest) -> ChatResponse:
        s = Session(json.loads(request.state))
        try:
            if request.mode == "rewind":
                s.rewind(request.nodeId)
            else:
                s.reopen(request.nodeId)
        except StepError as exc:
            return self._respond(request.evaluationId, s, validation_error=str(exc))
        return self._respond(request.evaluationId, s)

    # ---- internos ---------------------------------------------------------------
    @staticmethod
    def _evidence_info(node: Dict[str, Any], info: Dict[str, Any], confirmed: bool = False) -> Dict[str, Any]:
        base = node["id"].split("#")[0]
        scope = node["id"].split("#", 1)[1] if "#" in node["id"] else ""
        return {"code": base, "nodeId": node["id"], "scope": scope, "area": scope or None, "equipo": None,
                "count": info.get("count") or 1, "extracted": info.get("extracted") or {}, "confirmed": confirmed}

    def _respond(self, evaluation_id: str, s: Session, validation_error: Optional[str] = None,
                 last_evidence: Optional[Dict[str, Any]] = None, processed: Optional[List[str]] = None,
                 answered_id: Optional[str] = None) -> ChatResponse:
        cur = s.current()
        done = cur is not None and cur["kind"] == "fin"
        node: Optional[Dict[str, Any]] = None
        notices: List[Dict[str, Any]] = []
        counts = s.counts()
        if cur is not None and not done:
            node = node_prompt(s, cur)
            ev_step = cur["kind"] in ("ev", "check", "rcard", "links", "summary") or cur["id"] == "EVO" or __import__("re").match(r"^P28[bcu]?#", cur["id"]) is not None
            if ev_step:
                node["evidenceNumber"] = min(counts["ea"] + 1, counts["e"])
                node["evidenceTotal"] = counts["e"]
            else:
                node["questionNumber"] = min(counts["qa"] + 1, counts["q"])
                node["questionTotal"] = counts["q"]
            node["questionsTotal"] = counts["q"]
            node["evidencesTotal"] = counts["e"]
        if answered_id is not None:
            notices = s.alerts_between(answered_id, cur if not done else None)
        percent = 100 if done or (cur and cur["kind"] == "summary") else s.percent()
        answered = counts["qa"] + counts["ea"]
        proposal = None
        answers = _partial_answers(s)
        if done:
            proposal = build_proposal(s)
            answers = _completed_answers(s)
        itype = node.get("inputType") if node else None
        return ChatResponse(
            evaluationId=evaluation_id, currentStep=answered,
            currentQuestionKey=node["nodeId"] if node else None, currentQuestion=node["text"] if node else None,
            currentInputType=InputType(itype) if itype else None,
            currentOptions=[o["label"] for o in node.get("options", [])] or None if node else None,
            answeredQuestions=answered, totalQuestions=counts["q"] + counts["e"],
            progressPercent=percent, completed=done, answers=answers, proposal=proposal,
            state=json.dumps(s.state, ensure_ascii=False), node=node, validationError=validation_error,
            lastEvidence=last_evidence, crossChecks=[], followUps=[], processedImages=processed, notices=notices,
        )


# ---- respuestas legibles y propuesta ---------------------------------------------
def _partial_answers(s: Session) -> Dict[str, str]:
    X = s.X
    out: Dict[str, str] = {}
    if X.nombre:
        out["establishment_name"] = X.nombre
    if X.dir:
        out["address"] = str(X.dir)
    if X.rubL:
        out["establishment_type"] = X.rubL
    if X.encargado:
        out["visita.contacto"] = X.encargado
    if X.celular:
        out["visita.telefono"] = X.celular
    return out


def _completed_answers(s: Session) -> Dict[str, str]:
    out = _partial_answers(s)
    X = s.X
    out.update({
        "visita.razonSocial": X.razon or "", "visita.ruc": X.ruc or "", "visita.local": X.nombre or "", "negocio.estado": X.estadoL or "",
        "internet.conexion": X.conL or "", "internet.plan": fmt(X.plan) if X.plan else "", "cajas": str(X.cajas or 0),
        "impresoras": str(len(X.printers or [])),
    })
    out[STATE_KEY] = json.dumps(s.state, ensure_ascii=False)
    return out


def eq_list(R) -> List[Dict[str, Any]]:
    m: Dict[str, int] = {}
    for i in R.it:
        if i.eq:
            m[i.eq] = m.get(i.eq, 0) + 1
    return [{"n": k, "c": v} for k, v in m.items()]


def build_proposal(s: Session) -> ChatProposal:
    X, R = s.X, s.R
    sc = s.scores()
    return ChatProposal(
        summary=resumen_ia(X, R),
        asIsFindings=[i.t for i in R.it if i.tipo != "REC"],
        recommendations=[f"{i.t}. {i.d}" for i in R.it if i.tipo != "AVISO"],
        equipment=[EquipmentRecommendation(name=e["n"], description="", quantity=e["c"]) for e in eq_list(R)],
        topologyText="", topology=None, score=sc.g,
    )
