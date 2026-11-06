"""Endpoints del chat técnico: POST /chat/start y POST /chat/answer (el
gateway los consume tal cual), más la metadata de preguntas y el documento
de la minuta."""
import base64
import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from typing import List

from app.chat import adjunto
from app.chat.engine import ChatEngine
from app.chat.map_model import MapDocument, apply_command, from_topology
from app.chat.minuta_doc import MinutaDocument, build_minuta_document
from app.chat.topology import build_state_topology
from app.chat.schemas import ChatAmendRequest, ChatAnswerRequest, ChatEditRequest, ChatResponse, ChatStartRequest
from app.chat.sim import flow
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
        falta = [i.split("#", 1)[-1] for i in s.pending_later()]
        if falta:
            # fotos obligatorias dejadas con «Subir después»: la minuta no se genera hasta subirlas. El gateway ya
            # rechaza el PDF cuando viene `missingMandatory` («No se puede generar la minuta: falta …»).
            return {"missingMandatory": falta}
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


class AdjuntoRequest(BaseModel):
    evaluationId: str
    state: str
    tipo: Optional[str] = None          # ruc | comp | recibo | tarjeta | frontis (si el usuario lo eligió)
    imagesBase64: List[str] = []


class AdjuntoUsarRequest(BaseModel):
    evaluationId: str
    state: str
    campos: List[Dict[str, Any]]        # filas marcadas, con el valor ya corregido por el usuario


def _validar_nodo(s: Session, nodo: str, v: str) -> str:
    fn = {"P01b": flow._valid_ruc, "P05": flow._valid_cel, "P05b": flow._valid_mail}.get(nodo)
    return fn(re.sub(r"\s+", "", v) if nodo in ("P01b", "P05") else v) if fn else ""


@router.post("/adjunto")
def leer_adjunto(req: AdjuntoRequest) -> Dict[str, Any]:
    s = Session(json.loads(req.state))
    r = adjunto.leer(req.tipo, req.imagesBase64)
    if r["status"] != "OK" or not r["tipo"]:
        return {"status": r["status"] if r["status"] != "OK" else "TIPO", "tipos": {k: t["l"] for k, t in adjunto.TIPOS.items()}}
    return {"status": "OK", "tipo": r["tipo"], "titulo": adjunto.TIPOS[r["tipo"]]["l"], "nota": adjunto.TIPOS[r["tipo"]].get("nota"),
            "campos": adjunto.campos(r["tipo"], r["valores"], s.A, lambda nodo, v: _validar_nodo(s, nodo, v))}


@router.post("/adjunto/usar", response_model=ChatResponse)
def usar_adjunto(req: AdjuntoUsarRequest) -> ChatResponse:
    s = Session(json.loads(req.state))
    pre = s.state.setdefault("pre", {})
    for c in req.campos:
        if s.A.get(c["nodeId"]) is None:
            err = _validar_nodo(s, c["nodeId"], str(c.get("valor") or ""))
            if not err:
                pre[c["nodeId"]] = adjunto.a_prefill(c)
    s.apply_prefill()
    return _sim._respond(req.evaluationId, s)
