"""Rutas del Asistente IA 0.0.7 (las llama el gateway; la persistencia, los roles y la validación están en el gateway)."""
import base64
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.asistente import aprendizaje, extraer, plan, soporte
from app.asistente.texto import es_criterio

router = APIRouter(tags=["Asistente IA"])
LRN = re.compile(r"(qu[eé]\s+(has\s+)?aprendi(ste|do)|lo\s+que\s+aprendiste|aprendizajes?\s+(de\s+)?hoy|qu[eé]\s+(cosas\s+)?nuevas?\s+aprendiste)", re.I)
NUEVA = re.compile(r"\b(redact|gener|cre[ae]|arm[ae]|haz|hacer|elabor|nueva)\w*\b[^.]*\bminuta", re.I)


# ---------- plan de cambios de una minuta ----------
class PlanRequest(BaseModel):
    texto: str
    impresoras: List[Dict[str, Any]] = Field(default_factory=list, description="[{name, con}] de la minuta")


@router.post("/minutas/cambios/plan")
def plan_de_cambios(req: PlanRequest) -> Dict[str, Any]:
    return plan.plan_cambios(req.texto, req.impresoras)


# ---------- minuta de soporte ----------
class SoporteEvaluarRequest(BaseModel):
    motivo: str = ""
    hechos: List[str] = Field(default_factory=list)
    evidencias: List[str] = Field(default_factory=list, description="nombres de archivo; la lectura real la hace la visión")


@router.post("/asistente/soporte/evaluar")
def soporte_evaluar(req: SoporteEvaluarRequest) -> Dict[str, Any]:
    L = soporte.reglas_sugeridas(req.motivo, req.hechos)
    pr = L["lectura"]["impresoras"]
    return {"reglas": L["reglas"], "resultados": {k: soporte.resultado(k, L["reglas"][k], L) for k, _ in soporte.REGLAS},
            "estadoSugerido": soporte.estado_sugerido(L["reglas"], req.hechos), "impresoras": pr,
            "credenciales": L["lectura"]["credenciales"], "evidencias": [dict(archivo=e, **soporte.leer_evidencia(e, pr)) for e in req.evidencias]}


class SoporteMinutaRequest(BaseModel):
    cliente: str = ""
    local: str = ""
    direccion: str = ""
    fecha: str = ""
    tecnico: str = ""
    empresa: str = "IDBI"
    validadaPor: Optional[str] = None
    antecedentes: List[Dict[str, Any]] = Field(default_factory=list)
    motivo: str = ""
    puntos: List[str] = Field(default_factory=list)
    hechos: List[str] = Field(default_factory=list)
    evidencias: List[Dict[str, Any]] = Field(default_factory=list)
    reglas: Dict[str, str] = Field(default_factory=dict)
    estado: Optional[str] = None
    recs: List[Dict[str, str]] = Field(default_factory=list)
    pasos: List[Dict[str, str]] = Field(default_factory=list)
    notas: List[str] = Field(default_factory=list)
    credenciales: List[Dict[str, str]] = Field(default_factory=list)


@router.post("/asistente/soporte/minuta")
def soporte_minuta(req: SoporteMinutaRequest) -> Dict[str, Any]:
    if req.estado and req.estado not in soporte.ESTADOS:
        raise HTTPException(422, "estado debe ser OP, OPP u OBS")
    if len(req.hechos) < len(req.puntos):
        raise HTTPException(422, "falta lo realizado en algún punto del alcance")
    return soporte.documento(req.model_dump())


# ---------- aprendizaje del día y fichas ----------
class AprendizajeRequest(BaseModel):
    rol: str = "adm"
    visitas: List[Dict[str, Any]] = Field(default_factory=list)
    reglasExistentes: List[str] = Field(default_factory=list)
    notas: List[Dict[str, str]] = Field(default_factory=list)
    sugerencias: List[str] = Field(default_factory=list)
    totalReglas: int = 0
    totalMinutas: int = 0
    fichas: int = 0


def _solo_admin(rol: str) -> None:
    if rol not in ("adm", "admin", "ADMIN", "Administrador"):
        raise HTTPException(403, "Solo el administrador revisa lo aprendido y decide si se agregan reglas o preguntas.")


@router.post("/aprendizaje/hoy")
def aprendizaje_hoy(req: AprendizajeRequest) -> Dict[str, Any]:
    _solo_admin(req.rol)
    return aprendizaje.hoy(req.visitas, req.reglasExistentes, req.notas, req.sugerencias, req.totalReglas, req.totalMinutas, req.fichas)


class AplicarRequest(BaseModel):
    rol: str = "adm"
    casos: List[Dict[str, Any]]
    solo: Optional[str] = Field(None, description="reglas | preguntas | null")


@router.post("/aprendizaje/aplicar")
def aprendizaje_aplicar(req: AplicarRequest) -> Dict[str, Any]:
    _solo_admin(req.rol)
    return aprendizaje.aplicar(req.casos, req.solo)


class FichasRequest(BaseModel):
    rol: str = "adm"
    casos: List[Dict[str, Any]]
    admin: str
    empresa: str = "IDBI"
    inicio: int = 1


@router.post("/conocimiento/fichas")
def conocimiento_fichas(req: FichasRequest) -> Dict[str, Any]:
    _solo_admin(req.rol)
    fs = aprendizaje.fichas(req.casos, req.admin, req.empresa, req.inicio)
    return {"fichas": fs, "pdfBase64": base64.b64encode(aprendizaje.pdf(fs)).decode()}


# ---------- «Redacta una minuta nueva…» ----------
class ExtraerRequest(BaseModel):
    texto: str
    adjuntos: List[str] = Field(default_factory=list, description="tipos de evidencia ya adjuntados (Frontis del local, Speedtest…)")


@router.post("/asistente/extraer")
def asistente_extraer(req: ExtraerRequest) -> Dict[str, Any]:
    """Borrador de minuta a partir del texto del técnico: datos, conexiones de red, contenido y evidencias que faltan."""
    return extraer.borrador(req.texto, req.adjuntos)


# ---------- mensaje libre al Asistente IA ----------
class MensajeRequest(BaseModel):
    rol: str = "tec"
    texto: str
    contexto: Dict[str, Any] = Field(default_factory=dict, description="reglas activas, minutas recientes y base de conocimiento")


SYSTEM = ("Eres el Asistente IA de una app de visitas técnicas de red para puntos de venta. Respondes en español, breve y concreto, "
          "con las reglas de la empresa y la base de conocimiento que te pasan como contexto. No cambias criterios de todas las minutas: "
          "eso lo hace el administrador en Preguntas y reglas. Las contraseñas registradas sí se muestran en la minuta.")


def _chatgpt(texto: str, contexto: Dict[str, Any]) -> Optional[str]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
        r = OpenAI(api_key=key).chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "system", "content": SYSTEM}, {"role": "system", "content": f"Contexto: {contexto}"}, {"role": "user", "content": texto}],
            temperature=0.2)
        return r.choices[0].message.content
    except Exception:  # noqa: BLE001 — sin conexión con OpenAI responde con las reglas
        return None


@router.post("/asistente/mensaje")
def asistente_mensaje(req: MensajeRequest) -> Dict[str, Any]:
    t = req.texto.strip()
    if LRN.search(t):
        if req.rol not in ("adm", "admin", "Administrador"):
            return {"tipo": "texto", "texto": "Esa consulta es del administrador: él revisa lo aprendido y decide si se agregan reglas o preguntas. "
                                             "Si aprendiste algo en una visita, cuéntamelo y se lo envío como sugerencia."}
        return {"tipo": "aprendizaje", "texto": "Revisando lo aprendido hoy.", "accion": "POST /aprendizaje/hoy"}
    if NUEVA.search(t) and not re.search(r"actualiz|modific|corrig|cambi", t, re.I):
        if re.search(r"soporte|incidencia", t, re.I):
            return {"tipo": "soporte", "texto": "¿De qué cliente es la visita de soporte? Escribe el nombre del local o la razón social."}
        if not re.search(r"implementaci", t, re.I):
            return {"tipo": "tipo_minuta", "texto": "¿Qué minuta vas a redactar?", "opciones": ["Implementación", "Soporte / incidencia"]}
    if es_criterio(t):
        return {"tipo": "criterio", "texto": "Eso cambia el criterio de todas las minutas (formato, reglas o textos de recomendaciones), no los datos de un local. "
                                            "No se hace desde el chat: lo hace el administrador en Preguntas y reglas o el equipo de desarrollo.",
                "accion": "abrir_preguntas_y_reglas" if req.rol in ("adm", "admin") else "sugerencia_al_administrador"}
    r = _chatgpt(t, req.contexto)
    return {"tipo": "texto", "texto": r or "No encontré esa respuesta en las reglas de la app ni en las minutas guardadas; conviene confirmarla con tu supervisor.",
            "fuente": "chatgpt" if r else "reglas"}
