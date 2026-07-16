"""Motor conversacional de 20 nodos y seam de generación de propuesta.

El progreso por nodos es siempre propio (determinista). La generación de la
propuesta es intercambiable vía CHAT_PROPOSAL_ENGINE:
  - 'builtin' (por defecto): motor de reglas local.
  - 'flowise': delega en una instancia Flowise (con fallback a reglas).
  - 'openai': delega en la API de OpenAI (con fallback a reglas).
"""
import logging
from typing import Callable, Dict

from app.chat.config import settings
from app.chat.nodes import NODES, TOTAL_NODES, node_at
from app.chat.proposal import generate_proposal as rule_based_proposal
from app.chat.schemas import ChatAnswerRequest, ChatProposal, ChatResponse

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


class ChatEngine:
    """Recorre el grafo de 20 nodos y, al finalizar, genera la propuesta."""

    def __init__(self, proposal_generator: ProposalGenerator | None = None):
        self._generate = proposal_generator or get_proposal_generator()

    def start(self, evaluation_id: str) -> ChatResponse:
        first = NODES[0]
        return ChatResponse(
            evaluationId=evaluation_id,
            currentStep=0,
            currentQuestionKey=first.key,
            currentQuestion=first.question,
            currentInputType=first.input_type,
            currentOptions=first.options,
            answeredQuestions=0,
            totalQuestions=TOTAL_NODES,
            progressPercent=0,
            completed=False,
            answers={},
        )

    def answer(self, request: ChatAnswerRequest) -> ChatResponse:
        # Si ya se superó el último nodo, cerrar directamente.
        if request.currentStep >= TOTAL_NODES:
            return self._completed(request.evaluationId, dict(request.answers))

        current = NODES[request.currentStep]
        updated = dict(request.answers)
        if request.answer.strip():
            updated[current.key] = request.answer.strip()

        next_step = request.currentStep + 1
        answered = len(updated)
        progress = int(answered / TOTAL_NODES * 100)

        if next_step >= TOTAL_NODES:
            return self._completed(request.evaluationId, updated)

        nxt = node_at(next_step)
        return ChatResponse(
            evaluationId=request.evaluationId,
            currentStep=next_step,
            currentQuestionKey=nxt.key,
            currentQuestion=nxt.question,
            currentInputType=nxt.input_type,
            currentOptions=nxt.options,
            answeredQuestions=answered,
            totalQuestions=TOTAL_NODES,
            progressPercent=progress,
            completed=False,
            answers=updated,
        )

    def _completed(self, evaluation_id: str, answers: Dict[str, str]) -> ChatResponse:
        proposal = self._generate(answers)
        return ChatResponse(
            evaluationId=evaluation_id,
            currentStep=TOTAL_NODES,
            currentQuestionKey=None,
            currentQuestion=None,
            currentInputType=None,
            currentOptions=None,
            answeredQuestions=len(answers),
            totalQuestions=TOTAL_NODES,
            progressPercent=100,
            completed=True,
            answers=answers,
            proposal=proposal,
        )
