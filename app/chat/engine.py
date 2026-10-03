"""Motor conversacional del flujo de 76 nodos y seam de generación de propuesta.

El avance por nodos es siempre propio (determinista, ver flow_engine.py). La generación de la
propuesta es intercambiable vía CHAT_PROPOSAL_ENGINE:
  - 'builtin' (por defecto): motor de reglas local.
  - 'flowise': delega en una instancia Flowise (con fallback a reglas).
  - 'openai': delega en la API de OpenAI (con fallback a reglas).
"""
import json
import re
import logging
from datetime import date
from typing import Tuple, Any, Callable, Dict, List, Optional

from app.chat.config import settings
from app.chat import checks
from app.chat.evidence import analyze_evidence
from app.chat.flow_engine import BLOCK_ORDER, FLOW, Session, StepError, new_state
from app.chat.legacy_adapter import completed_answers, legacy_answers, partial_answers
from app.chat.proposal import generate_proposal as rule_based_proposal
from app.chat.schemas import (
    ChatAmendRequest, ChatAnswerRequest, ChatProposal, ChatResponse, ChatStartRequest, InputType,
)
from app.chat.topology import build_state_topology, topology_to_text
from app.geocoding import geocode

logger = logging.getLogger("idbi.chat")

# Firma del generador de propuesta: recibe las respuestas y devuelve la propuesta.
ProposalGenerator = Callable[[Dict[str, str]], ChatProposal]


def _flowise_proposal(answers: Dict[str, str]) -> ChatProposal:
    """Enriquecer la propuesta con Flowise; si falla, usar reglas."""
    base = rule_based_proposal(answers)
    if not settings.flowise_url:
        logger.warning("CHAT_PROPOSAL_ENGINE=flowise pero FLOWISE_URL no está configurada; se usan reglas.")
        return base
    try:
        import httpx  # import diferido: solo se requiere en modo flowise

        prompt = (
            "Eres un ingeniero de redes. A partir de estos datos de un local "
            "gastronómico, resume el diagnóstico y prioriza recomendaciones:\n"
            + "\n".join(f"- {k}: {v}" for k, v in answers.items())
        )
        url = settings.flowise_url.rstrip("/")
        if settings.flowise_chatflow_id:
            url = f"{url}/api/v1/prediction/{settings.flowise_chatflow_id}"
        headers = {}
        if settings.flowise_api_key:
            headers["Authorization"] = f"Bearer {settings.flowise_api_key}"

        resp = httpx.post(url, json={"question": prompt}, headers=headers,
                          timeout=settings.request_timeout)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("text") or data.get("answer") or ""
        if text:
            base.summary = text.strip()
        return base
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fallo al consultar Flowise (%s); se usan reglas.", exc)
        return base


def _openai_proposal(answers: Dict[str, str]) -> ChatProposal:
    """Enriquecer la propuesta con OpenAI; si falla, usar reglas."""
    base = rule_based_proposal(answers)
    if not settings.openai_api_key:
        logger.warning("CHAT_PROPOSAL_ENGINE=openai pero OPENAI_API_KEY no está configurada; se usan reglas.")
        return base
    try:
        from openai import OpenAI  # import diferido

        client = OpenAI(api_key=settings.openai_api_key)
        prompt = (
            "Resume en un párrafo el diagnóstico técnico de red para este local "
            "y no inventes datos:\n"
            + "\n".join(f"- {k}: {v}" for k, v in answers.items())
        )
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = completion.choices[0].message.content
        if text:
            base.summary = text.strip()
        return base
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fallo al consultar OpenAI (%s); se usan reglas.", exc)
        return base


def get_proposal_generator() -> ProposalGenerator:
    if settings.proposal_engine == "flowise":
        return _flowise_proposal
    if settings.proposal_engine == "openai":
        return _openai_proposal
    return rule_based_proposal


def _without_covered(cross: List[str], follow: List[Dict[str, Any]]) -> List[str]:
    """Si una pregunta de confirmación ya cubre el aviso (proveedor distinto),
    no se repite como tarjeta ámbar."""
    if any(f["key"] == "provider" for f in follow):
        return [m for m in cross if "proveedor" not in m.lower()]
    return cross


class ChatEngine:
    """Avanza el flujo de nodos un paso por llamada y, al finalizar, genera la propuesta."""

    def __init__(self, proposal_generator: ProposalGenerator | None = None):
        self._generate = proposal_generator or get_proposal_generator()

    # ---- entradas HTTP ----------------------------------------------------
    def start(self, request: ChatStartRequest) -> ChatResponse:
        state = new_state({
            "today": request.today or date.today().strftime("%d/%m/%Y"),
            "technician": request.technicianName or "",
        })
        return self._respond(request.evaluationId, state)

    def answer(self, request: ChatAnswerRequest) -> ChatResponse:
        state: Dict[str, Any] = json.loads(request.state)
        session = Session(state)
        before = session.prompt()
        node_id, scope = before.get("nodeId"), before.get("scope", "")

        evidence_info: Optional[Dict[str, Any]] = None
        processed: Optional[List[str]] = None
        advance_evidence: Optional[Dict[str, Any]] = None
        if before.get("kind") == "evidence" and request.photosBase64:
            photos = request.photosBase64[: before.get("maxFiles", 3)]
            result = analyze_evidence(before["evidenceCode"], photos)
            processed = result.processedImages
            advance_evidence = {"count": len(photos), "extracted": result.extracted}

        try:
            session.advance(request.answer, advance_evidence)
        except StepError as exc:
            return self._respond(request.evaluationId, state, validation_error=str(exc))

        cross: List[str] = []
        if advance_evidence is not None:
            code = before["evidenceCode"]
            cross = checks.upload_warnings(state, code, scope, advance_evidence["extracted"])
            if code == "E8":
                self._flag_documented(state, advance_evidence["extracted"])
            follow = checks.follow_ups(state, code, advance_evidence["extracted"])
            cross = _without_covered(cross, follow)
            ctx = before.get("ctx") or {}
            evidence_info = {
                "code": code, "nodeId": node_id, "scope": scope,
                "area": ctx.get("area"), "equipo": ctx.get("equipo"),
                "count": advance_evidence["count"], "extracted": advance_evidence["extracted"],
            }

        if node_id == "P03":
            self._geocode(state)

        return self._respond(
            request.evaluationId, state,
            last_evidence=evidence_info, cross_checks=cross, processed_images=processed,
            follow_ups=follow if advance_evidence is not None else None,
        )

    def amend(self, request: ChatAmendRequest) -> ChatResponse:
        """"Corregir" una evidencia o responder una pregunta de confirmación."""
        state: Dict[str, Any] = json.loads(request.state)
        evidence_info: Optional[Dict[str, Any]] = None
        cross: List[str] = []

        if request.evidenceCode:
            found = [e for e in state["evidences"]
                     if e["code"] == request.evidenceCode and e["scope"] == request.evidenceScope]
            if found:
                evidence = found[-1]
                evidence["extracted"].update(request.fields)
                if request.evidenceCode == "E8":
                    self._flag_documented(state, evidence["extracted"])
                cross = checks.upload_warnings(state, evidence["code"], evidence["scope"], evidence["extracted"])
                evidence_info = {
                    "code": evidence["code"], "nodeId": evidence["nodeId"], "scope": evidence["scope"],
                    "area": evidence.get("area"), "equipo": evidence.get("equipo"),
                    "count": evidence["count"], "extracted": evidence["extracted"],
                }

        if request.clarificationKey:
            state.setdefault("clarifications", {})[request.clarificationKey] = request.clarificationAnswer or ""

        follow = None
        if evidence_info and not request.clarificationKey:
            follow = checks.follow_ups(state, evidence_info["code"], evidence_info["extracted"])
            cross = _without_covered(cross, follow)
        return self._respond(request.evaluationId, state, last_evidence=evidence_info, cross_checks=cross,
                             follow_ups=follow)

    def _counters(self, state: Dict[str, Any], prompt: Dict[str, Any], answered: int) -> Dict[str, int]:
        """Contadores del encabezado. T es una estimación y los loops (cajas, impresoras,
        áreas) la hacen crecer.

        - "Pregunta N de T": solo preguntas fijas (sin las evidencias ni los seguimientos
          condicionales con sufijo a/b/c).
        - "Evidencia N de M": las evidencias, aparte.
        - `percent`: avance sobre todos los pasos (preguntas + evidencias).
        """
        nodes = FLOW.nodes
        current_block = prompt.get("blockIndex", 0)
        done_ids = {k.split("#")[0] for k in state["answers"] if "." not in k}

        def fixed(node: Dict[str, Any], kind: str) -> bool:
            return node["kind"] == kind and re.fullmatch(r"P\d+", node["id"]) is not None

        def remaining(kind: str) -> int:
            return sum(
                1 for n in nodes.values()
                if fixed(n, kind) and n["id"] not in done_ids and n["id"] != prompt.get("nodeId")
                and n.get("block") in BLOCK_ORDER and BLOCK_ORDER.index(n["block"]) + 1 >= current_block
            )

        def count_answered(kind: str) -> int:
            return sum(
                1 for k in state["answers"]
                if "." not in k and fixed(nodes.get(k.split("#")[0], {"kind": "", "id": ""}), kind)
            )

        questions_done, evidence_done = count_answered("question"), count_answered("evidence")
        current = nodes.get(prompt.get("nodeId"), {})
        on_question = fixed(current, "question") if current else False
        on_evidence = prompt.get("kind") == "evidence"

        # Sobre una evidencia o un seguimiento el contador de preguntas no avanza.
        number = questions_done + (1 if on_question else 0)
        total = questions_done + (1 if on_question else 0) + remaining("question")
        out = {"questionNumber": max(1, number), "questionTotal": max(1, total)}
        if on_evidence:
            out["evidenceNumber"] = evidence_done + 1
            out["evidenceTotal"] = evidence_done + 1 + remaining("evidence")
        steps_left = remaining("question") + remaining("evidence") + (1 if on_question or on_evidence else 0)
        out["percent"] = min(95, int(answered / max(1, answered + steps_left) * 100))
        return out

    def _flag_documented(self, state: Dict[str, Any], extracted: Dict[str, Any]) -> None:
        known = checks.known_ips(state)
        names = checks.known_labels(state)
        for device in extracted.get("dispositivos") or []:
            device["documentado"] = checks.is_documented(state, device, known)
            if names.get(device.get("ip")):
                device["etiqueta"] = names[device["ip"]]

    # ---- internos ---------------------------------------------------------
    def _geocode(self, state: Dict[str, Any]) -> None:
        a = state["answers"]
        state["answers"]["visita.ubicacion"] = geocode(a.get("P02") or a.get("P01", ""), a.get("P03"))

    def _respond(
        self, evaluation_id: str, state: Dict[str, Any],
        validation_error: Optional[str] = None,
        last_evidence: Optional[Dict[str, Any]] = None,
        cross_checks: Optional[List[str]] = None,
        processed_images: Optional[List[str]] = None,
        follow_ups: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatResponse:
        session = Session(state)
        answered = len([k for k in state["answers"] if "." not in k])
        done = bool(state["done"])
        prompt = {} if done else session.prompt()
        percent = 100
        if prompt:
            counters = self._counters(state, prompt, answered)
            percent = counters.pop("percent")
            prompt.update(counters)
        block_idx = prompt.get("blockIndex", len(BLOCK_ORDER)) if not done else len(BLOCK_ORDER)

        proposal: Optional[ChatProposal] = None
        if done:
            proposal = self._generate(legacy_answers(state))
            proposal.topology = build_state_topology(state)
            proposal.topologyText = topology_to_text(proposal.topology)
            answers = completed_answers(state)
        else:
            answers = partial_answers(state)

        itype = prompt.get("inputType")
        return ChatResponse(
            evaluationId=evaluation_id,
            currentStep=answered,
            currentQuestionKey=prompt.get("nodeId"),
            currentQuestion=prompt.get("text"),
            currentInputType=InputType(itype) if itype else None,
            currentOptions=[o["label"] for o in prompt.get("options", [])] or None,
            answeredQuestions=answered,
            totalQuestions=len(BLOCK_ORDER),
            progressPercent=100 if done else percent,
            completed=done,
            answers=answers,
            proposal=proposal,
            state=json.dumps(state, ensure_ascii=False),
            node=prompt or None,
            validationError=validation_error,
            lastEvidence=last_evidence,
            crossChecks=cross_checks or [],
            followUps=follow_ups or [],
            processedImages=processed_images,
        )
