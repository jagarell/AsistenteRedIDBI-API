"""Endpoints del chat técnico. El contrato HTTP se mantiene compatible con el
gateway: POST /chat/start y POST /chat/answer."""
from fastapi import APIRouter

from app.chat.engine import ChatEngine
from app.chat.schemas import ChatAnswerRequest, ChatResponse, ChatStartRequest

router = APIRouter(prefix="/chat", tags=["Technical Chat"])

_engine = ChatEngine()


@router.post("/start", response_model=ChatResponse)
def start_chat(request: ChatStartRequest) -> ChatResponse:
    return _engine.start(request.evaluationId)


@router.post("/answer", response_model=ChatResponse)
def answer_chat(request: ChatAnswerRequest) -> ChatResponse:
    return _engine.answer(request)
