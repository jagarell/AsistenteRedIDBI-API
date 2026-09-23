from typing import Dict

from fastapi import FastAPI
from app.chat.nodes import NODES
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.analysis import AnalysisResult, compute_analysis
from app.chat.checklist import EvidenceChecklistSeed, build_evidence_checklist
from app.chat.router import router as chat_router
from app.vision import PhotoAnalyzeRequest, PhotoAnalyzeResult, analyze_photo

app = FastAPI(
    title="IDBI IA Service",
    version="1.1.0",
)

# CORS: el gateway es el consumidor principal; en producción restringir orígenes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


class AnalyzeRequest(BaseModel):
    evaluationId: int
    restaurantName: str
    capturedPhotos: int = 0
    answers: Dict[str, str] = {}
    # Hallazgos de visión por foto de evidencia, ej.
    # {"router": {"brand": "TP-Link", "model": "Archer C6"}}. Ver app/vision.py.
    detectedEquipment: Dict[str, dict] = {}


@app.get("/")
def root():
    return {"status": "OK", "service": "IDBI FastAPI"}


@app.get("/health")
def health():
    return {"status": "OK", "message": "IA service ready"}


@app.post("/analyze", response_model=AnalysisResult)
def analyze(request: AnalyzeRequest):
    return compute_analysis(
        request.answers,
        request.restaurantName,
        detected_equipment=request.detectedEquipment,
    )


@app.post("/analyze-photo", response_model=PhotoAnalyzeResult)
def analyze_photo_endpoint(request: PhotoAnalyzeRequest):
    return analyze_photo(request.category, request.imageBase64)


class EvidenceChecklistSeedRequest(BaseModel):
    answers: Dict[str, str] = {}


@app.post("/evidence-checklist/seed", response_model=EvidenceChecklistSeed)
def evidence_checklist_seed(request: EvidenceChecklistSeedRequest):
    return build_evidence_checklist(request.answers)


@app.get("/chat/nodes")
def chat_nodes():
    """Metadata liviana (clave + pregunta) de los nodos del chat, para que el
    gateway pueda mostrar las respuestas guardadas con su texto de pregunta
    sin duplicar las preguntas en Java."""
    return [{"key": node.key, "question": node.question} for node in NODES if not node.auto]
