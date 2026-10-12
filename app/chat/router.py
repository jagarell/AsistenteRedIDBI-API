"""Endpoints del chat técnico: POST /chat/start y POST /chat/answer (el
gateway los consume tal cual), más la metadata de preguntas y el documento
de la minuta."""
import base64
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.chat.engine import ChatEngine
from app.chat.map_model import MapDocument, apply_command, from_topology
from app.chat.minuta_doc import MinutaDocument, build_minuta_document
from app.chat.topology import build_state_topology
from app.chat.schemas import ChatAmendRequest, ChatAnswerRequest, ChatEditRequest, ChatResponse, ChatStartRequest
from app.chat.sim.engine import Session, is_v2
from app.chat.sim.map import build_map, map_height, to_document
from app.chat.sim.minuta import build_document
from app.chat.sim.service import SimChat

router = APIRouter(prefix="/chat", tags=["Technical Chat"])

_engine = ChatEngine()   # evaluaciones iniciadas con el flujo anterior (estado sin versión)
_sim = SimChat()         # flujo vigente (simulador)


def _is_new(state: str) -> bool:
    try:
        return is_v2(json.loads(state))
    except ValueError:
        return False


@router.post("/start", response_model=ChatResponse)
def start_chat(request: ChatStartRequest) -> ChatResponse:
    return _engine.start(request) if request.legacy else _sim.start(request)


@router.post("/answer", response_model=ChatResponse)
def answer_chat(request: ChatAnswerRequest) -> ChatResponse:
    return _sim.answer(request) if _is_new(request.state) else _engine.answer(request)


@router.post("/amend", response_model=ChatResponse)
def amend_chat(request: ChatAmendRequest) -> ChatResponse:
    return _sim.amend(request) if _is_new(request.state) else _engine.amend(request)


@router.post("/edit", response_model=ChatResponse)
def edit_chat(request: ChatEditRequest) -> ChatResponse:
    return _sim.edit(request)


class MinutaDocumentRequest(BaseModel):
    # JSON del `state` del flujo (viaja en answers["__state"] al completarse el chat).
    state: str
    # Mapa editado por el técnico (si no hay, se dibuja el automático) y las
    # fotos de evidencia que lleva, por id de imagen del mapa (base64).
    map: Optional[MapDocument] = None
    mapImages: Dict[str, str] = {}
    # Ediciones de la minuta (datos principales, observaciones, propuesta) y datos del momento (quién validó, fecha).
    edits: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


@router.post("/minuta-document")
def minuta_document(request: MinutaDocumentRequest):
    images = {k: base64.b64decode(v) for k, v in request.mapImages.items()}
    state = json.loads(request.state)
    if is_v2(state):
        s = Session(state)
        return build_document(s.A, state["ctx"], request.edits, request.meta,
                              request.map.model_dump() if request.map else None, images)
    return build_minuta_document(state, request.map, images)


class MapGenerateRequest(BaseModel):
    state: str


@router.post("/map/generate", response_model=MapDocument)
def map_generate(request: MapGenerateRequest) -> MapDocument:
    """"Generar mapa con IA": mapa automático a partir de lo levantado en el chat."""
    state = json.loads(request.state)
    if is_v2(state):
        s = Session(state)
        m = build_map(s.X)
        doc = to_document(m)
        doc["canvasH"] = map_height(m)
        return MapDocument(**doc)
    return from_topology(build_state_topology(state))


class MapCommandRequest(BaseModel):
    map: MapDocument
    command: str


class MapCommandResponse(BaseModel):
    map: MapDocument
    reply: str


@router.post("/map/command", response_model=MapCommandResponse)
def map_command(request: MapCommandRequest) -> MapCommandResponse:
    """"Pide un cambio al mapa…": aplica una orden en lenguaje natural."""
    doc, reply = apply_command(request.map, request.command)
    return MapCommandResponse(map=doc, reply=reply)
