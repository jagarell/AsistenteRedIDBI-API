"""Endpoints del chat técnico: POST /chat/start y POST /chat/answer (el
gateway los consume tal cual), más la metadata de preguntas y el documento
de la minuta."""
import json

from fastapi import APIRouter
from pydantic import BaseModel

from app.chat.engine import ChatEngine
from app.chat.minuta_doc import MinutaDocument, build_minuta_document
from app.chat.schemas import ChatAmendRequest, ChatAnswerRequest, ChatResponse, ChatStartRequest

router = APIRouter(prefix="/chat", tags=["Technical Chat"])

_engine = ChatEngine()


@router.post("/start", response_model=ChatResponse)
def start_chat(request: ChatStartRequest) -> ChatResponse:
    return _engine.start(request)


@router.post("/answer", response_model=ChatResponse)
def answer_chat(request: ChatAnswerRequest) -> ChatResponse:
    return _engine.answer(request)


@router.post("/amend", response_model=ChatResponse)
def amend_chat(request: ChatAmendRequest) -> ChatResponse:
    return _engine.amend(request)


class MinutaDocumentRequest(BaseModel):
    # JSON del `state` del flujo (viaja en answers["__state"] al completarse el chat).
    state: str


@router.post("/minuta-document", response_model=MinutaDocument)
def minuta_document(request: MinutaDocumentRequest) -> MinutaDocument:
    return build_minuta_document(json.loads(request.state))
