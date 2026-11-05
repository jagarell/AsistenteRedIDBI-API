"""«¿Qué aprendiste hoy?» (solo administrador): lo aprendido de las visitas de evaluación, de soporte y de información del día,
con propuestas de reglas y preguntas nuevas, y la ficha de aprendizaje en PDF para la base de conocimiento."""
import re
from datetime import date
from typing import Any, Dict, List, Optional

# Aprendizajes que se reconocen en el texto de las visitas: regla y pregunta que se proponen (o la regla que ya lo cubre)
CONOCIMIENTO = [
    {"clave": "ip_fija", "si": [r"\bip\b|dhcp", r"cambi|reinici|dej[oó] de imprimir|no la encontr|autom[aá]tica"],
     "aprendizaje": "Toda impresora de red debe tener IP fija y, si el router lo permite, reservada. La impresora de respaldo por WiFi lleva una IP distinta y registrada en el sistema de impresiones.",
     "regla": {"id": "R_IP_FIJA", "t": "IP fija en las impresoras de red", "tipo": "Observación",
               "d": "Configurar la IP fija en la impresora y pedir al proveedor que la reserve en el router; registrar la misma IP en el sistema de impresiones.",
               "c": "Una impresora de red o WiFi tiene la IP asignada por el router (DHCP)", "q": "P28f", "v": "La asigna el router (DHCP)"},
     "pregunta": {"id": "P28f", "seccion": "Impresoras", "seccionId": "E", "texto": "¿La IP de la impresora es fija o la asigna el router?", "tipo": "Una opción",
                  "opciones": ["Fija (configurada en la impresora)", "La asigna el router (DHCP)", "No se sabe"], "cuando": "por cada impresora de red o WiFi"}},
    {"clave": "zona_temporada", "si": [r"temporada|verano|piscina"],
     "aprendizaje": "Preguntar si hay zonas que se usan solo por temporada; antes de reabrirlas, probar su impresora y su WiFi.",
     "regla": {"id": "R_ZONA_TEMP", "t": "Zona de temporada", "tipo": "Recomendación", "d": "Antes de la temporada, probar la impresora y el WiFi de esa zona y confirmar su IP.",
               "c": "Hay una zona que se usa solo por temporada (por ejemplo, piscina en verano)", "q": "P11t", "v": "Sí"},
     "pregunta": {"id": "P11t", "seccion": "Negocio y canales", "seccionId": "B", "texto": "¿Alguna zona se usa solo por temporada (por ejemplo, piscina en verano)?",
                  "tipo": "Sí / No", "opciones": ["Sí", "No"], "cuando": "siempre que haya más de una zona de atención"}},
    {"clave": "wifi_repetidor", "si": [r"repetidor", r"impresora|imprim"],
     "aprendizaje": "Las impresoras de preparación van por cable de red; por WiFi solo como respaldo.", "cubierta": "Ya lo cubre la regla R51 (impresoras de preparación por cable)."},
]


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


def hoy(visitas: List[Dict[str, Any]], reglas_existentes: List[str], notas: Optional[List[Dict[str, str]]] = None,
        sugerencias: Optional[List[str]] = None, total_reglas: int = 0, total_minutas: int = 0, fichas: int = 0) -> Dict[str, Any]:
    """visitas: [{id, tipo: evaluacion|soporte|informacion, local, tecnico, texto}]. Devuelve los casos con su propuesta."""
    casos: List[Dict[str, Any]] = []
    for v in visitas:
        if v.get("tipo") not in ("soporte", "informacion"):
            continue
        t = _norm(v.get("texto") or "")
        for k in CONOCIMIENTO:
            if all(re.search(p, t) for p in k["si"]) and not any(c["clave"] == k["clave"] for c in casos):
                c = {"id": f"{v.get('id')}:{k['clave']}", "clave": k["clave"], "tipo": "Soporte" if v["tipo"] == "soporte" else "Información",
                     "local": v.get("local"), "tecnico": v.get("tecnico"), "caso": v.get("caso") or v.get("texto"),
                     "causa": v.get("causa"), "solucion": v.get("solucion"), "aprendizaje": k["aprendizaje"]}
                if k.get("regla"):
                    c["regla"], c["pregunta"] = k["regla"], k["pregunta"]
                    c["agregada"] = k["regla"]["id"] in reglas_existentes
                else:
                    c["cubierta"] = k["cubierta"]
                casos.append(c)
    pend = [c for c in casos if c.get("regla") and not c.get("agregada")]
    n_ev = len([v for v in visitas if v.get("tipo") == "evaluacion"])
    n_s = len([v for v in visitas if v.get("tipo") == "soporte"])
    n_i = len([v for v in visitas if v.get("tipo") == "informacion"])
    return {"visitas": {"evaluacion": n_ev, "soporte": n_s, "informacion": n_i}, "reglasActivas": total_reglas, "minutasTerminadas": total_minutas,
            "fichas": fichas, "casos": casos, "notas": notas or [], "sugerencias": sugerencias or [],
            "sugerencia": (f"Te sugiero agregar {len(pend)} {'regla' if len(pend) == 1 else 'reglas'} y {len(pend)} {'pregunta' if len(pend) == 1 else 'preguntas'}. ¿Procedo? "
                           "También puedo guardar este conocimiento y generar la ficha de aprendizaje en PDF.") if pend else
                          "Las reglas y preguntas sugeridas ya están agregadas. Puedo guardar este conocimiento y generar la ficha de aprendizaje en PDF."}


def aplicar(casos: List[Dict[str, Any]], solo: Optional[str] = None) -> Dict[str, Any]:
    """Reglas (activas) y preguntas que el gateway guarda en Preguntas y reglas, con auditoría «aprobada por el administrador»."""
    reglas = [c["regla"] for c in casos if c.get("regla") and solo != "preguntas"]
    preguntas = [c["pregunta"] for c in casos if c.get("pregunta") and solo != "reglas"]
    return {"reglas": [dict(r, activa=True, origen="asistente_ia") for r in reglas], "preguntas": [dict(p, origen="asistente_ia") for p in preguntas]}


def fichas(casos: List[Dict[str, Any]], admin: str, empresa: str = "IDBI", inicio: int = 1, hoy_: Optional[date] = None) -> List[Dict[str, Any]]:
    d = hoy_ or date.today()
    out = []
    for j, c in enumerate(casos):
        f = dict(c)
        f["codigo"] = f"FA-{d:%Y%m%d}-{inicio + j:02d}"
        f["fecha"] = f"{d:%d/%m/%Y}"
        f["admin"] = admin
        f["empresa"] = empresa
        if c.get("regla"):
            f["estado"] = (f"Regla {c['regla']['id']} y pregunta {c['pregunta']['id']} agregadas en Preguntas y reglas" if c.get("agregada")
                           else f"Regla {c['regla']['id']} y pregunta {c['pregunta']['id']} sugeridas (sin agregar)")
        else:
            f["estado"] = c.get("cubierta") or ""
        out.append(f)
    return out


# ---------------- PDF de la ficha de aprendizaje (sin librerías) ----------------
def _enc(s: Any) -> str:
    s = str(s if s is not None else "")
    for a, b in (("–", "-"), ("—", "-"), ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), ("→", "->"), ("…", "...")):
        s = s.replace(a, b)
    s = "".join(ch for ch in s if ord(ch) < 256)
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _col(h: str) -> str:
    n = int(h[1:], 16)
    return " ".join(f"{((n >> sh) & 255) / 255:.3f}" for sh in (16, 8, 0))


def _wrap(s: str, size: float, w: float, bold: bool = False) -> List[str]:
    n = max(10, int(w / (size * (0.56 if bold else 0.51))))
    out: List[str] = []
    for par in str(s).split("\n"):
        ln = ""
        for wd in par.split():
            if len((ln + " " + wd).strip()) > n:
                if ln:
                    out.append(ln)
                ln = wd
            else:
                ln = (ln + " " + wd).strip()
        out.append(ln)
    return out


def pdf(fs: List[Dict[str, Any]]) -> bytes:
    W, H, M = 595, 842, 46
    pages: List[List[str]] = []
    st = {"ops": None, "y": 0.0, "f": None}

    def T(x: float, y: float, s: str, sz: float, b: bool = False, c: str = "#1F2937") -> None:
        st["ops"].append(f"BT {_col(c)} rg /{'F2' if b else 'F1'} {sz} Tf {x:.1f} {y:.1f} Td ({_enc(s)}) Tj ET")

    def Rc(x: float, y: float, w: float, h: float, c: str) -> None:
        st["ops"].append(f"{_col(c)} rg {x} {y:.1f} {w} {h} re f")

    def new_page(f: Dict[str, Any]) -> None:
        st["ops"] = []
        pages.append(st["ops"])
        Rc(0, H - 86, W, 86, "#0E2A52")
        T(M, H - 44, "FICHA DE APRENDIZAJE", 19, True, "#FFFFFF")
        T(M, H - 66, f"{f['empresa']} · Asistente de Red · Base de conocimiento", 10, False, "#C9D6EA")
        T(W - M - 150, H - 44, f["codigo"], 11, True, "#FFFFFF")
        T(W - M - 150, H - 62, "Fecha: " + f["fecha"], 9.5, False, "#C9D6EA")
        st["y"] = H - 112

    def need(h: float) -> None:
        if st["y"] - h < 70:
            new_page(st["f"])

    def kv(rows: List[List[str]]) -> None:
        cw = (W - 2 * M) / 2
        for i, (k, v) in enumerate(rows):
            if i % 2 == 0:
                need(36)
            x = M + (i % 2) * cw
            T(x, st["y"], k.upper(), 8, True, "#6B7A90")
            T(x, st["y"] - 14, v or "—", 10.5)
            if i % 2 == 1 or i == len(rows) - 1:
                st["y"] -= 36
        st["y"] -= 8

    def sec(t: str, txt: str, tone: str = "#EEF3FA") -> None:
        L = _wrap(txt, 10.5, W - 2 * M - 24)
        need(30 + len(L) * 14)
        Rc(M, st["y"] - 4, W - 2 * M, 22, tone)
        Rc(M, st["y"] - 4, 4, 22, "#1A5FD0")
        T(M + 12, st["y"] + 3, t, 11, True, "#0E2A52")
        st["y"] -= 24
        for ln in L:
            T(M + 12, st["y"], ln, 10.5)
            st["y"] -= 14
        st["y"] -= 10

    for f in fs:
        st["f"] = f
        new_page(f)
        T(M, st["y"], "Caso de soporte" if f.get("tipo") == "Soporte" else "Información de visita", 15, True, "#0E2A52")
        st["y"] -= 26
        kv([["Tipo de visita", f.get("tipo") or ""], ["Local", f.get("local") or ""], ["Técnico", f.get("tecnico") or ""], ["Registrado por", f.get("admin") or ""]])
        sec("Casuística (qué pasó)", f.get("caso") or "")
        if f.get("causa"):
            sec("Causa", f["causa"])
        if f.get("solucion"):
            sec("Solución aplicada", f["solucion"])
        sec("Aprendizaje", f.get("aprendizaje") or "", "#E8F5E9")
        if f.get("regla"):
            r, q = f["regla"], f["pregunta"]
            sec("Cómo se aplica en las próximas visitas", f"Regla {r['id']} «{r['t']}» ({r['tipo']}): {r['d']}\nSe activa cuando: {r['c']}.\n"
                                                       f"Pregunta {q['id']} en {q['seccion']}: «{q['texto']}» ({' / '.join(q['opciones'])}).")
        elif f.get("cubierta"):
            sec("Cómo se aplica en las próximas visitas", f["cubierta"])
        sec("Estado", f"{f.get('estado')}. Guardado en la base de conocimiento por {f.get('admin')} el {f.get('fecha')}; el Asistente IA lo usa para responder y para sugerir reglas.", "#FFF8E1")
    for i, p in enumerate(pages):
        st["ops"] = p
        Rc(M, 40, W - 2 * M, 0.8, "#C9D2DE")
        T(M, 26, f"Generada por el Asistente IA · {fs[i if i < len(fs) else 0]['empresa'] if fs else ''} · {fs[0]['fecha'] if fs else ''}", 8.5, False, "#6B7A90")
        T(W - M - 60, 26, f"Página {i + 1} de {len(pages)}", 8.5, False, "#6B7A90")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "PAGES",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for p in pages:
        s = "\n".join(p)
        objs.append(f"<< /Length {len(s.encode('latin-1'))} >>\nstream\n{s}\nendstream")
        c = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {c} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offs = []
    for i, o in enumerate(objs):
        offs.append(len(out.encode("latin-1")))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    x = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF"
    return out.encode("latin-1")
