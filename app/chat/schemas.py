"""Modelos de entrada/salida del chat. La respuesta es un superconjunto
compatible (aditivo) del contrato previo consumido por el gateway."""
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.chat.nodes import InputType


# --- Peticiones ---
class ChatStartRequest(BaseModel):
    evaluationId: str


class ChatAnswerRequest(BaseModel):
    evaluationId: str
    currentStep: int = Field(ge=0)
    answer: str = ""
    answers: Dict[str, str] = {}


# --- Topología estructurada ---
class ConnectionType(str, Enum):
    CABLE_RED = "CABLE_RED"
    WIFI = "WIFI"
    USB_BLUETOOTH = "USB_BLUETOOTH"


class LinkStatus(str, Enum):
    OPERATIVO = "OPERATIVO"
    CON_FALLA = "CON_FALLA"


class TopologyNode(BaseModel):
    id: str
    label: str
    type: str          # internet | router | switch | access_point | pos | printer | camera | computer
    level: int         # nivel jerárquico (0 = internet, 1 = router, 2 = switch, 3 = endpoints)


class TopologyLink(BaseModel):
    source: str
    target: str
    connectionType: ConnectionType
    status: LinkStatus = LinkStatus.OPERATIVO


class Topology(BaseModel):
    nodes: List[TopologyNode] = []
    links: List[TopologyLink] = []


# --- Propuesta ---
class EquipmentRecommendation(BaseModel):
    name: str
    description: str
    quantity: int


class ChatProposal(BaseModel):
    summary: str
    recommendations: List[str]
    equipment: List[EquipmentRecommendation]
    topologyText: str                     # se conserva por compatibilidad
    topology: Optional[Topology] = None   # topología estructurada (nuevo)
    score: Optional[int] = None           # 0-100


class ChatResponse(BaseModel):
    evaluationId: str
    currentStep: int
    currentQuestionKey: Optional[str]
    currentQuestion: Optional[str]
    currentInputType: Optional[InputType] = None
    currentOptions: Optional[List[str]] = None
    answeredQuestions: int
    totalQuestions: int
    progressPercent: int
    completed: bool
    answers: Dict[str, str]
    proposal: Optional[ChatProposal] = None
