"""Modelos de entrada/salida del chat.

El motor es el de flujo de 76 nodos (ver flow_engine.py): el cliente manda el
`state` opaco que recibió en la respuesta anterior más la respuesta al nodo
actual, y recibe el siguiente nodo. Los campos `current*`/`answers`/`proposal`
se conservan con la misma forma de antes para los consumidores existentes."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InputType(str, Enum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    CHOICE = "CHOICE"              # selección única
    MULTI_SELECT = "MULTI_SELECT"  # selección múltiple (valores separados por coma)
    YES_NO = "YES_NO"
    EVIDENCE = "EVIDENCE"          # 1 a 3 fotos leídas por IA
    ALERT = "ALERT"                # aviso con botón "Entendido"
    SUMMARY = "SUMMARY"            # resumen final con Generar minuta / mapa


# --- Peticiones ---
class ChatStartRequest(BaseModel):
    evaluationId: str
    # Prefills de P06 (fecha) y P07 (técnico): los pone el gateway.
    technicianName: Optional[str] = None
    today: Optional[str] = None


class ChatAnswerRequest(BaseModel):
    evaluationId: str
    # Estado opaco devuelto por la respuesta anterior (JSON en string).
    state: str
    # Texto de la respuesta (opciones múltiples unidas por coma). Para
    # EVIDENCE se ignora; para SUMMARY es la acción elegida.
    answer: str = ""
    # Solo en nodos EVIDENCE: 1..3 fotos en base64.
    photosBase64: List[str] = Field(default_factory=list)


class ChatAmendRequest(BaseModel):
    """Corrige lo leído en una evidencia ("Corregir") y/o responde una pregunta
    de confirmación del asistente (proveedor distinto, dispositivo sin documentar)."""
    evaluationId: str
    state: str
    evidenceCode: Optional[str] = None
    evidenceScope: str = ""
    # Campos de `extracted` a sobrescribir (valores ya tipados: números, textos...).
    fields: Dict[str, Any] = Field(default_factory=dict)
    clarificationKey: Optional[str] = None
    clarificationAnswer: Optional[str] = None


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
    detail: Optional[str] = None   # 2ª línea (IP, modelo...) — la usa el mapa de la minuta
    pending: bool = False          # equipo por adquirir/instalar (borde punteado)
    floor: Optional[int] = None    # piso, cuando el negocio tiene más de uno


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
    # Pendiente de catálogo real de precios de IDBI — mismo patrón que
    # OPENAI_API_KEY/RUC_VALIDATION: el campo existe pero se manda null hasta
    # que exista un catálogo real; nunca se inventa un precio.
    unitPrice: float | None = None


class ChatProposal(BaseModel):
    summary: str
    asIsFindings: List[str] = []          # diagnóstico del estado actual (AS-IS)
    recommendations: List[str]            # propuesta objetivo (TO-BE)
    equipment: List[EquipmentRecommendation]
    topologyText: str                     # se conserva por compatibilidad
    topology: Optional[Topology] = None   # topología estructurada (nuevo)
    score: Optional[int] = None           # 0-100


class ChatResponse(BaseModel):
    evaluationId: str
    # Pregunta/nodo actual, en la forma plana de siempre.
    currentStep: int                       # nodos respondidos hasta ahora
    currentQuestionKey: Optional[str]      # id del nodo (P22, A_RASPBERRY, ...)
    currentQuestion: Optional[str]
    currentInputType: Optional[InputType] = None
    currentOptions: Optional[List[str]] = None   # etiquetas (compatibilidad)
    currentUnit: Optional[str] = None
    # Progreso por bloque (A..I): las ramas hacen que el total real varíe.
    answeredQuestions: int
    totalQuestions: int
    progressPercent: int
    completed: bool
    answers: Dict[str, str]
    proposal: Optional[ChatProposal] = None

    # --- Contrato del flujo de nodos ---
    state: Optional[str] = None            # estado opaco para la próxima llamada
    node: Optional[Dict[str, Any]] = None  # prompt completo del nodo actual
    validationError: Optional[str] = None  # respuesta inválida: el nodo no avanzó
    # Evidencia recién procesada: {code, nodeId, scope, area, equipo, count, extracted}
    lastEvidence: Optional[Dict[str, Any]] = None
    # Avisos de validación cruzada para mostrar como tarjetas en el chat.
    crossChecks: List[str] = Field(default_factory=list)
    # Preguntas de confirmación tras una evidencia: [{key, text, options[]}].
    followUps: List[Dict[str, Any]] = Field(default_factory=list)
    # Solo E3: imágenes con las credenciales ya desenfocadas (base64). El
    # gateway las guarda en vez de las originales y no las reenvía a la app.
    processedImages: Optional[List[str]] = None
