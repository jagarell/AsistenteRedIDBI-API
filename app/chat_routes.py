from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/chat", tags=["Technical Chat"])


QUESTIONS = [
    {
        "key": "establishment",
        "question": "¿Cuál es el nombre y tipo de establecimiento que vamos a evaluar?"
    },
    {
        "key": "internet",
        "question": "¿Qué proveedor de internet utiliza y cuál es la velocidad contratada?"
    },
    {
        "key": "router",
        "question": "¿Qué router o módem tiene actualmente y dónde está instalado?"
    },
    {
        "key": "switches",
        "question": "¿Cuenta con switches? Indica cantidad, modelo o número de puertos."
    },
    {
        "key": "devices",
        "question": "¿Cuántos POS, impresoras, cámaras y computadoras necesitan conexión?"
    },
    {
        "key": "wifi",
        "question": "¿En qué áreas necesita cobertura WiFi y dónde presenta problemas de señal?"
    },
    {
        "key": "security",
        "question": "¿Necesita red de invitados, VLAN, firewall o conexión de respaldo?"
    }
]


class ChatStartRequest(BaseModel):
    evaluationId: str


class ChatAnswerRequest(BaseModel):
    evaluationId: str
    currentStep: int = Field(ge=0)
    answer: str
    answers: Dict[str, str] = {}


class EquipmentRecommendation(BaseModel):
    name: str
    description: str
    quantity: int


class ChatProposal(BaseModel):
    summary: str
    recommendations: List[str]
    equipment: List[EquipmentRecommendation]
    topologyText: str


class ChatResponse(BaseModel):
    evaluationId: str
    currentStep: int
    currentQuestionKey: Optional[str]
    currentQuestion: Optional[str]
    answeredQuestions: int
    totalQuestions: int
    progressPercent: int
    completed: bool
    answers: Dict[str, str]
    proposal: Optional[ChatProposal] = None


@router.post("/start", response_model=ChatResponse)
def start_chat(request: ChatStartRequest):
    return ChatResponse(
        evaluationId=request.evaluationId,
        currentStep=0,
        currentQuestionKey=QUESTIONS[0]["key"],
        currentQuestion=QUESTIONS[0]["question"],
        answeredQuestions=0,
        totalQuestions=len(QUESTIONS),
        progressPercent=0,
        completed=False,
        answers={}
    )


@router.post("/answer", response_model=ChatResponse)
def answer_chat(request: ChatAnswerRequest):
    if request.currentStep >= len(QUESTIONS):
        return build_completed_response(
            request.evaluationId,
            request.answers
        )

    current_question = QUESTIONS[request.currentStep]

    updated_answers = dict(request.answers)
    updated_answers[current_question["key"]] = request.answer.strip()

    next_step = request.currentStep + 1
    answered_questions = len(updated_answers)

    progress = int(
        answered_questions / len(QUESTIONS) * 100
    )

    if next_step >= len(QUESTIONS):
        return build_completed_response(
            request.evaluationId,
            updated_answers
        )

    next_question = QUESTIONS[next_step]

    return ChatResponse(
        evaluationId=request.evaluationId,
        currentStep=next_step,
        currentQuestionKey=next_question["key"],
        currentQuestion=next_question["question"],
        answeredQuestions=answered_questions,
        totalQuestions=len(QUESTIONS),
        progressPercent=progress,
        completed=False,
        answers=updated_answers
    )


def build_completed_response(
        evaluation_id: str,
        answers: Dict[str, str]
) -> ChatResponse:
    proposal = generate_proposal(answers)

    return ChatResponse(
        evaluationId=evaluation_id,
        currentStep=len(QUESTIONS),
        currentQuestionKey=None,
        currentQuestion=None,
        answeredQuestions=len(QUESTIONS),
        totalQuestions=len(QUESTIONS),
        progressPercent=100,
        completed=True,
        answers=answers,
        proposal=proposal
    )


def generate_proposal(
        answers: Dict[str, str]
) -> ChatProposal:
    all_text = " ".join(answers.values()).lower()

    recommendations: List[str] = []
    equipment: List[EquipmentRecommendation] = []

    if any(word in all_text for word in [
        "wifi", "señal", "cobertura", "punto ciego",
        "cocina", "terraza", "segundo piso"
    ]):
        recommendations.append(
            "Realizar un estudio de cobertura e instalar puntos de acceso WiFi adicionales."
        )
        equipment.append(
            EquipmentRecommendation(
                name="Access Point WiFi 6",
                description="Punto de acceso administrable para ampliar cobertura.",
                quantity=2
            )
        )

    if any(word in all_text for word in [
        "pos", "caja", "impresora"
    ]):
        recommendations.append(
            "Separar el tráfico de POS y cajas mediante una VLAN exclusiva."
        )

    if any(word in all_text for word in [
        "cámara", "camaras", "cámaras", "poe"
    ]):
        recommendations.append(
            "Utilizar un switch PoE administrable para cámaras y access points."
        )
        equipment.append(
            EquipmentRecommendation(
                name="Switch PoE administrable",
                description="Switch de 24 puertos con soporte VLAN y PoE.",
                quantity=1
            )
        )

    if any(word in all_text for word in [
        "respaldo", "redundancia", "segundo enlace",
        "dos proveedores"
    ]):
        recommendations.append(
            "Implementar un segundo enlace de internet con failover automático."
        )

    if any(word in all_text for word in [
        "invitados", "clientes"
    ]):
        recommendations.append(
            "Crear una red WiFi de invitados aislada de la red administrativa."
        )

    if any(word in all_text for word in [
        "firewall", "seguridad", "vlan"
    ]):
        recommendations.append(
            "Implementar firewall y segmentación de red por VLAN."
        )

    if not recommendations:
        recommendations.extend([
            "Utilizar un router empresarial con firewall.",
            "Centralizar las conexiones en un switch administrable.",
            "Implementar monitoreo básico de disponibilidad."
        ])

    if not equipment:
        equipment.extend([
            EquipmentRecommendation(
                name="Router empresarial",
                description="Router con firewall y administración centralizada.",
                quantity=1
            ),
            EquipmentRecommendation(
                name="Switch administrable",
                description="Switch de 24 puertos con soporte VLAN.",
                quantity=1
            )
        ])

    establishment = answers.get(
        "establishment",
        "el establecimiento"
    )

    summary = (
        f"Para {establishment} se recomienda una infraestructura "
        f"segmentada, administrable y preparada para crecimiento."
    )

    topology_text = (
        "Proveedor de Internet → Router/Firewall → "
        "Switch administrable → POS, impresoras, cámaras y Access Points"
    )

    return ChatProposal(
        summary=summary,
        recommendations=recommendations,
        equipment=equipment,
        topologyText=topology_text
    )