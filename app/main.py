from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

app = FastAPI(
    title="IDBI IA Service",
    version="1.0.0"
)

class AnalyzeRequest(BaseModel):
    evaluationId: int
    restaurantName: str
    capturedPhotos: int = 0

class AnalysisItem(BaseModel):
    title: str
    status: str
    score: int
    description: str
    color: str

class AnalyzeResponse(BaseModel):
    globalScore: int
    evaluatedAreas: int
    attentionRequired: int
    results: List[AnalysisItem]
    summary: str
    recommendations: List[str]

@app.get("/")
def home():
    return {
        "status": "OK",
        "service": "FastAPI IA"
    }

@app.get("/health")
def health():
    return {
        "status": "OK",
        "message": "IA service ready"
    }

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    return {
        "globalScore": 72,
        "evaluatedAreas": 4,
        "attentionRequired": 2,
        "results": [
            {
                "title": "Conectividad de Red",
                "status": "Buena",
                "score": 78,
                "description": "Enlace principal estable. Se recomienda redundancia.",
                "color": "blue"
            },
            {
                "title": "Infraestructura Física",
                "status": "Regular",
                "score": 62,
                "description": "Cableado estructurado incompleto en cocina.",
                "color": "orange"
            },
            {
                "title": "Equipamiento",
                "status": "Óptimo",
                "score": 85,
                "description": "Hardware en buen estado, 3 años de antigüedad.",
                "color": "green"
            },
            {
                "title": "Cobertura WiFi",
                "status": "Deficiente",
                "score": 55,
                "description": "Puntos ciegos en área de cocina y terraza.",
                "color": "red"
            }
        ],
        "summary": "El análisis indica oportunidades de mejora en cobertura WiFi y cableado estructurado.",
        "recommendations": [
            "Implementar segmentación VLAN: POS, WiFi clientes y gestión.",
            "Configurar QoS para priorizar tráfico crítico.",
            "Instalar 2 APs adicionales en zona de cocina.",
            "Implementar redundancia de enlace.",
            "Configurar portal cautivo para WiFi de clientes.",
            "Monitoreo proactivo con alertas 24/7."
        ]
    }