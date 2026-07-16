from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.chat.router import router as chat_router

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
def root():
    return {"status": "OK", "service": "IDBI FastAPI"}


@app.get("/health")
def health():
    return {"status": "OK", "message": "IA service ready"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    # NOTA: el diagnóstico por área sigue siendo un ejemplo estructurado; el
    # análisis real (AnalysisEngine) se implementará sobre estos datos. Al menos
    # el resumen usa el nombre real del establecimiento recibido del gateway.
    results = [
        AnalysisItem(title="Conectividad de Red", status="Buena", score=78,
                     description="Enlace principal estable. Se recomienda redundancia.",
                     color="blue"),
        AnalysisItem(title="Infraestructura Física", status="Regular", score=62,
                     description="Cableado estructurado incompleto en cocina.",
                     color="orange"),
        AnalysisItem(title="Equipamiento", status="Óptimo", score=85,
                     description="Hardware en buen estado.",
                     color="green"),
        AnalysisItem(title="Cobertura WiFi", status="Deficiente", score=55,
                     description="Puntos ciegos en área de cocina y terraza.",
                     color="red"),
    ]
    global_score = round(sum(r.score for r in results) / len(results))
    attention = sum(1 for r in results if r.score < 65)

    return AnalyzeResponse(
        globalScore=global_score,
        evaluatedAreas=len(results),
        attentionRequired=attention,
        results=results,
        summary=(
            f"El análisis de {request.restaurantName} indica oportunidades de "
            "mejora en cobertura WiFi y cableado estructurado."
        ),
        recommendations=[
            "Implementar segmentación VLAN: POS, WiFi clientes y gestión.",
            "Configurar QoS para priorizar tráfico crítico.",
            "Instalar 2 APs adicionales en zona de cocina.",
            "Implementar redundancia de enlace.",
            "Configurar portal cautivo para WiFi de clientes.",
            "Monitoreo proactivo con alertas 24/7.",
        ],
    )
