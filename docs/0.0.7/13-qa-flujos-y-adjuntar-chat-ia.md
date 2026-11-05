# 0.0.7 · Parte 4 — QA de flujos por rol y «Adjuntar» en el Chat IA

Cambio que se agrega **después** de las Partes 1 (API), 2 (Gateway) y 3 (Android). Parte de esos tres repositorios ya en 0.0.7.
Nada se subió a GitHub: este documento lista los cambios para que el desarrollador los aplique a mano.

Orden: **API → Gateway → Android** (la web consume las mismas rutas del gateway).

---

## 1. Qué se probó

| Prueba | Cómo | Resultado |
|---|---|---|
| Chat IA: todos los caminos | 1400 evaluaciones automáticas con respuestas al azar: rubros, estados del local, cajas, impresoras, conexión, evidencias saltadas, WiFi y switch | Todas llegan a la minuta. El motor no deja nodos sin salida |
| Casos base del simulador | 5 casos completos | 5 de 5 terminan |
| Pantallas por rol (app) | 16 pantallas × técnico, supervisor y administrador | Sin errores |
| Pantallas por rol (web) | 11 tableros × 3 roles | 1 error: Notificaciones del técnico (punto 2.5) |
| Escritura real del usuario | Probé lo que escribe un técnico en campo: «no sé», «no lo tengo», una opción escrita a mano, una duda con «?» | 4 bloqueos (puntos 2.1 a 2.4) |
| Sin toda la información | Revisé las 77 preguntas: cuáles tienen salida si el técnico no tiene el dato. Después, 300 evaluaciones contestando «No lo sé ahora» u «Otro» con texto libre en las 12 preguntas del cliente | Antes: 12 preguntas obligaban a adivinar. Ahora: 300 de 300 llegan a la minuta, con los pendientes en Pasos a seguir |

El motor de preguntas no se traba solo. **Se traba con datos que el técnico no tiene en el local** o cuando escribe en vez de tocar.

---

## 2. Bloqueos encontrados y cambio a realizar

| # | Rol | Dónde | Qué pasa hoy | Cambio | Simulador |
|---|---|---|---|---|---|
| 2.1 | Técnico / supervisor / administrador (quien evalúa) | P01b «¿Cuál es el RUC?» | Si no tiene el RUC, cualquier texto da «El RUC debe tener 11 dígitos…». **No puede avanzar.** Termina inventando un RUC | Opción **«No lo tengo ahora»**. Escribir «no sé» hace lo mismo. Queda **«Por confirmar»** en la minuta y se agrega el paso del cliente «Enviar el RUC para completar la minuta». También puede **adjuntar la ficha RUC** | ✅ |
| 2.2 | Quien evalúa | P04 «¿Quién es el encargado?» | Sin salida si el encargado no está: se inventa un nombre | Opción **«No está en el local»** → «Por confirmar» + paso del cliente | ✅ |
| 2.3 | Quien evalúa | P01, P01c, P03, P05, P05b, P13, P15 | Hay que escribir a mano datos que ya están en papeles del local (ficha RUC, boleta, recibo de internet, tarjeta) | **Adjuntar** (sección 3): la IA lee el documento y responde la pregunta actual y las siguientes | ✅ |
| 2.4 | Quien evalúa | Preguntas con opciones (P08, P09, P12, P13, P15, P18…) | En la app el texto escrito se envía tal cual y la API responde «Elige una de las opciones». En la web la caja de texto está desactivada. Una duda («¿qué es el selftest?») no tiene dónde ir | Se puede **escribir**: se busca la opción (sin tildes ni mayúsculas, «500» → «500 Mbps», «no sé» → la opción «No sé/Saltar» si existe). Un número va al «Otro» numérico. Si termina en «?» se responde en **Ayuda** (no va a la minuta). Si no coincide, se avisa sin perder lo escrito | ✅ |
| 2.5 | Técnico (web) | Notificaciones | Falla al armar la lista (el técnico no tiene equipo). La web muestra **datos de ejemplo de un supervisor, con botones Validar y Rechazar** | El técnico ve sus minutas («Tu minuta de …»: esperando validación, en revisión, validada) y sus avisos, **sin acciones de validación** | ✅ |
| 2.6 | Quien evalúa | Barra de avance del Chat IA | Marca **75 % en la pregunta 4**: divide entre las preguntas ya armadas, no entre el total estimado. Con eso parece que falta poco | Calcular sobre el total estimado (preguntas + evidencias), como el contador «Pregunta N de ~T» | ✅ |
| 2.7 | Quien evalúa | 12 preguntas que dependen del cliente (sección 2.1) | Solo hay Sí/No u opciones fijas: si el encargado no sabe, el técnico **adivina** y eso cambia reglas, estado final y minuta | **«No lo sé ahora»** («Aún no lo decide» en P22b) y **«Otro (escribir)»** con texto libre. La respuesta queda «Por confirmar» o el texto escrito; el chat sigue por la rama prudente; se avisa al terminar y pasa a Pasos a seguir del cliente | ✅ |
| 2.8 | Quien evalúa | Plan de internet desconocido | Sin plan, la regla V01 calculaba 0 % y ponía «El internet no llega a lo contratado» | Sin plan no se compara: aviso «Plan de internet por confirmar» con la velocidad medida | ✅ |

### 2.1 Preguntas que dependen del cliente: «No lo sé ahora» y «Otro (escribir)»

El técnico no siempre tiene toda la información en la visita. En estas preguntas se agregan dos opciones:
- **«No lo sé ahora»** («Aún no lo decide» en P22b): la minuta muestra **«Por confirmar»**.
- **«Otro (escribir)»**: el usuario escribe la respuesta tal como se la dieron. La minuta muestra **ese texto**.

**Qué rama sigue el chat**
- Cuando el texto escrito es claro, el chat sigue por la rama que corresponde. Por ejemplo, «a veces en la noche» cuenta como **Sí**.
- Cuando no es claro, sigue la **rama prudente** y nunca toma la opción más común como cierta.

**Qué pasa al terminar**
- Lo no confirmado se lista al terminar el Chat IA.
- También pasa a Pasos a seguir del cliente: «Confirmar con ID: …».
- Se completa después con el Asistente IA, con «Actualizar una minuta».

| Pregunta | Rama prudente con «No lo sé ahora» | «Otro» con texto |
|---|---|---|
| P12 ¿Cuántas cajas hay o va a haber? | 1 caja | Toma el primer número entre 1 y 20 («2 ahora y una más en diciembre» → 2). Si no hay número válido: 1 caja y queda por confirmar |
| P12b ¿En caja saldrán comandas? | No | Sí/No según el texto; si no es claro, No + por confirmar |
| P15 Plan de internet | Sin plan: no se compara la velocidad (2.8) | Número entre 1 y 10000 Mbps («aprox 300» → 300); si no hay número, sin plan |
| P16 ¿Internet de respaldo? | «No sabe» (no cuenta como «No» para NO APTO) | Sí/No según el texto |
| P17 ¿Caídas de internet? | «No sabe» (no suma el motivo de caídas) | «a veces», «de vez en cuando», «sí…» → Sí |
| P09c ¿Mozos con tablet o celular? | Sí (se dimensiona el WiFi y el ancho de banda con tablets) | Sí/No según el texto |
| P47 ¿Cámaras en la red? | No (no se suman) | Sí/No según el texto |
| P47a ¿Cuántas cámaras? | 0 | Número entre 0 y 64 |
| P22g ¿El equipo de caja se queda en el local? | Sí | Sí/No según el texto |
| P22a ¿Ya cuenta con Raspberry? | No (se pregunta qué adquirirá) | Sí/No según el texto |
| P22b ¿Qué adquirirá el cliente? | «Aún no lo decide» (pendiente del cliente) | Raspberry/Laptop/PC si se nombra; si no, pendiente |
| P28h# ¿Ya tiene la impresora? | No (se recomienda adquirirla) | Sí/No según el texto |

Si el usuario **escribe** en la caja en vez de tocar:
- «no sé» elige «No lo sé ahora»;
- un texto que no es una opción se guarda como «Otro»;
- una pregunta con «?» va a Ayuda.

**API (`flow.py`, `engine.py`, `rules.py`)**
```python
# flow.py: en cada una de esas preguntas (YN = Sí/No)
PC = {"P12": 1, "P12b": "NO", "P15": "OTRO", "P16": "NS", "P17": "NS", "P09c": "SI", "P47": "NO", "P47a": 0,
      "P22g": "SI", "P22a": "NO", "P22b": "PEND", "P28h": "NO"}
TEMA = {"P12": "el número de cajas", "P12b": "si saldrán comandas en caja", "P15": "la velocidad del plan de internet",
        "P16": "si tiene internet de respaldo", "P17": "si el local tiene caídas de internet",
        "P09c": "si los mozos tomarán pedidos con tablet o celular", "P47": "si se conectarán cámaras a la red",
        "P47a": "cuántas cámaras irán conectadas a la red", "P22g": "si el equipo de caja se queda en el local",
        "P22a": "si ya cuenta con un Raspberry", "P22b": "qué equipo adquirirá para el sistema de impresiones",
        "P28h": "si ya tiene la impresora"}

def pc_opts(id_, opts):
    """Otro con texto (también en P12, P15 y P47a, que hoy solo aceptan números) + No lo sé ahora."""
    out = [dict(o, num=False, l="Otro (escribir)") if o.get("otro") else o for o in opts]
    if not any(o.get("otro") for o in out):
        out.append({"v": "OTRO", "l": "Otro (escribir)", "otro": True})
    out.append({"v": "NS52", "l": "Aún no lo decide" if id_ == "P22b" else "No lo sé ahora"})
    return out
```
```python
# engine.py · _parse (opciones): normaliza «No lo sé ahora» y «Otro» de estas preguntas
SI_RE = re.compile(r"^(s[ií]\b|claro|tiene\b|hay\b|a veces|algun|de vez|ocasional|frecuent|seguido|todos|siempre)", re.I)
NO_RE = re.compile(r"^(no\b|nunca|ningun|jam[aá]s)", re.I)
TOPE = {"P12": (1, 20), "P15": (1, 10000), "P47a": (0, 64)}

def norm_pc(id_, val):
    base = id_.split("#")[0]
    if base not in PC:
        return val
    if val["v"] == "NS52":
        return {"v": PC[base], "label": "Por confirmar", "pc": True}
    if val["v"] != "OTRO":
        return val
    t = val["label"].strip()
    if base in TOPE:
        m = re.search(r"\d+", t)
        k = int(m.group()) if m else None
        ok = k is not None and TOPE[base][0] <= k <= TOPE[base][1]
        return {"v": k if ok else PC[base], "label": t, "pc": not ok}
    if base == "P22b":
        m = "RASPBERRY" if re.search(r"rasp", t, re.I) else "LAPTOP" if re.search(r"laptop|port[aá]til", t, re.I) \
            else "PC" if re.search(r"\bpc\b|computador", t, re.I) else None
        return {"v": m or PC[base], "label": t, "pc": m is None}
    m = "SI" if SI_RE.match(t) else "NO" if NO_RE.match(t) else None
    return {"v": m or PC[base], "label": t, "pc": m is None}
```
Usar `norm_pc` al final de `_parse` de opciones (para «NS52» y «OTRO:<texto>»).
En P15, si `v` es número, `X.plan = v`; con `"OTRO"` y sin número, `X.plan = None`.
```python
# rules.py · V01: sin plan no se compara (2.8)
if not X.plan:
    V01 = None
    add({"id": "PLAN_PC", "tipo": "AVISO", "t": "Plan de internet por confirmar",
         "d": f"Mejor prueba por cable: {fmt(best)} Mbps. Falta el plan contratado para compararla (se cumple desde el 70 %, Ley 31207)."})
else:
    V01 = "CUMPLE" if pct >= 0.7 else "OBSERVADO"
# rules.py · gen_pasos: lo no confirmado
pend = [TEMA[k.split("#")[0]] + (f" ({k.split('#')[1]})" if "#" in k else "") for k, e in a.items()
        if k.split("#")[0] in TEMA and (e or {}).get("pc")]
if pend:
    P.append({"p": "Cliente", "t": f"Confirmar con ID: {'; '.join(pend)}."})
```
`service.py`:
- al llegar al FIN, agregar el aviso «Quedan por confirmar: …» (con el RUC y el encargado si quedaron «Por confirmar»);
- en `node_prompt` mandar las dos opciones nuevas, para que la app y la web las muestren como chips.

**Después de aplicarlo**, regenerar los golden del simulador (`tools/sim_oracle`: `gen.js`, `export.js`, `catalog.js`) con el `simulador.html` de este paquete. Las preguntas cambian de opciones y los golden anteriores ya no coinciden.

**Android y web**: no necesitan código nuevo para esto. Las opciones llegan en `node.options`, y «Otro (escribir)» ya abre la caja de texto.

### Recomendados (no se cambiaron; requieren decisión)

| # | Dónde | Qué pasa | Propuesta |
|---|---|---|---|
| R3 | E1c ipconfig / E1d escáner | Piden PC o laptop. Si la caja es tablet/Sunmi y el técnico no lleva laptop, no se dice qué hacer (sí se puede saltar) | Agregar al texto: «Si no hay PC ni laptop en el local, toca Saltar» |
| R4 | Preguntas de selección múltiple | No se puede escribir para agregar una zona sin tocar «Otro» | Igual que 2.4: lo escrito se agrega como opción marcada |
| R5 | Foto de la etiqueta del router (E2e) | `vision.py` tiene la orden de **no leer** SSID ni clave y los tapa en la foto. La minuta 0.0.7 **sí** muestra «Accesos y contraseñas», así que el técnico los escribe a mano en la tarjeta del router | Leer SSID y clave para la tarjeta del router (van a la minuta). Seguir tapándolos en la imagen del anexo |
| R6 | Web (todos los tableros) | Si el puente con la app falla, el tablero muestra en silencio sus **datos de ejemplo**. Así se originó 2.5 | Mostrar «No se pudo cargar» en vez de los datos de ejemplo |
| R7 | Web · Chat IA | El botón flotante «Volver a Inicio» tapa el porcentaje de avance | Moverlo debajo de la barra o dentro del menú ⋮ |

---

## 3. «Adjuntar» en el Chat IA (app y web)

### Cómo funciona

1. En el Chat IA hay un **clip** junto al micrófono, siempre activo. En las preguntas de datos del cliente aparece además un atajo:

   | Pregunta | Atajo | Lee |
   |---|---|---|
   | P01 razón social, P01b RUC | Adjuntar ficha RUC o comprobante | Razón social, RUC, nombre comercial, domicilio fiscal |
   | P01c nombre del local | Adjuntar foto del letrero | Nombre del local |
   | P03 dirección | Adjuntar boleta o factura del local | Razón social, RUC, nombre comercial, dirección del establecimiento |
   | P04, P05, P05b encargado | Adjuntar tarjeta del encargado | Nombre y cargo, celular, correo |
   | P13 proveedor, P15 plan | Adjuntar recibo de internet | Proveedor, velocidad del plan |

2. El usuario toma la foto o sube una imagen o PDF. Si no eligió el tipo, la IA lo reconoce y, si no está segura, lo pregunta.
3. Se abre **«Datos leídos del adjunto»**. Cada dato tiene una casilla y un campo editable:
   - Lo ya respondido aparece en gris.
   - La **dirección de la ficha RUC viene desmarcada**, porque es el domicilio fiscal y puede no ser la del local.
4. «Usar N datos» responde la pregunta actual. Las demás se responden **cuando el chat llega a ellas**, en orden y con las mismas validaciones:
   - un RUC inválido no se usa y se avisa;
   - las ramas del flujo no cambian.
5. Las respuestas que vienen del adjunto llevan un clip en la burbuja. Se corrigen tocándolas, como cualquier respuesta.
6. El archivo se guarda como **documento del cliente**, no como foto de la visita. No cuenta como evidencia obligatoria ni va al anexo de fotos.

Si escribe «no sé» en P01, P01c o P03, se abre el adjuntar con el tipo correcto.

### 3.1 API (FastAPI) — `AsistenteRedIDBI-API`

**Nuevo `app/chat/adjunto.py`**
```python
"""Lectura de documentos del cliente adjuntos en el Chat IA (ficha RUC, comprobante, recibo, tarjeta, letrero)."""
import json, logging, re
from typing import Any, Dict, List, Optional
from app.chat.config import settings  # el mismo settings que usa vision.py

logger = logging.getLogger(__name__)

# tipo -> [(nodo, etiqueta, clave que devuelve la IA)]
TIPOS: Dict[str, Dict[str, Any]] = {
    "ruc":     {"l": "Ficha RUC o consulta RUC (SUNAT)", "f": [("P01", "Razón social", "razonSocial"), ("P01b", "RUC", "ruc"),
                 ("P01c", "Nombre del local", "nombreComercial"), ("P03", "Dirección", "direccion")],
                "off": ["P03"], "nota": "La dirección de la ficha RUC es el domicilio fiscal: márcala solo si es la del local."},
    "comp":    {"l": "Boleta o factura del local", "f": [("P01", "Razón social", "razonSocial"), ("P01b", "RUC", "ruc"),
                 ("P01c", "Nombre del local", "nombreComercial"), ("P03", "Dirección", "direccion")]},
    "recibo":  {"l": "Recibo de internet", "f": [("P13", "Proveedor", "proveedor"), ("P15", "Plan", "planMbps")]},
    "tarjeta": {"l": "Tarjeta o datos del encargado", "f": [("P04", "Encargado", "encargado"), ("P05", "Celular", "celular"),
                 ("P05b", "Correo", "correo")]},
    "frontis": {"l": "Foto del frontis o letrero", "f": [("P01c", "Nombre del local", "nombreComercial")]},
}
# pregunta -> tipo sugerido (atajo debajo de la pregunta)
POR_NODO = {"P01": "ruc", "P01b": "ruc", "P01c": "frontis", "P03": "comp", "P04": "tarjeta", "P05": "tarjeta",
            "P05b": "tarjeta", "P13": "recibo", "P15": "recibo"}
PROV = {"movistar": "MOVISTAR", "claro": "CLARO", "entel": "ENTEL", "win": "WIN", "bitel": "BITEL"}


def leer(tipo: Optional[str], images_b64: List[str]) -> Dict[str, Any]:
    """Devuelve {tipo, valores{clave: texto}} o {status: 'UNAVAILABLE'} si no hay IA."""
    if not settings.openai_api_key:
        return {"status": "UNAVAILABLE", "tipo": tipo, "valores": {}}
    claves = sorted({c for t in TIPOS.values() for _, _, c in t["f"]})
    prompt = ("Lees un documento de un cliente peruano (ficha RUC de SUNAT, boleta o factura, recibo de internet, tarjeta de presentación "
              "o foto del letrero del local). Extrae SOLO lo claramente legible; si no se ve, usa null. No inventes. Responde un JSON con "
              f'"tipo" (uno de {list(TIPOS)}) y las claves {claves}. "ruc": 11 dígitos sin espacios. "planMbps": número. '
              '"encargado": "Nombre Apellido, cargo". "nombreComercial": nombre comercial o del letrero, no la razón social.')
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        content: List[dict] = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{i}"}} for i in images_b64[:3]]
        r = client.chat.completions.create(model=settings.openai_model, messages=[{"role": "user", "content": content}],
                                           max_tokens=500, response_format={"type": "json_object"})
        raw = json.loads(r.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falló la lectura del adjunto: %s", exc)
        return {"status": "UNAVAILABLE", "tipo": tipo, "valores": {}}
    t = tipo if tipo in TIPOS else (raw.get("tipo") if raw.get("tipo") in TIPOS else None)
    return {"status": "OK", "tipo": t, "valores": {k: (None if raw.get(k) in (None, "") else str(raw.get(k)).strip()) for k in claves}}


def campos(tipo: str, valores: Dict[str, Any], respondidas: Dict[str, Any], validar) -> List[Dict[str, Any]]:
    """Filas de la hoja «Datos leídos del adjunto». validar(nodo, valor) -> mensaje de error o ''."""
    t = TIPOS[tipo]
    out = []
    for nodo, etiqueta, clave in t["f"]:
        v = valores.get(clave)
        if v is None:
            continue
        err = validar(nodo, v)
        out.append({"nodeId": nodo, "label": etiqueta, "valor": v, "respondido": respondidas.get(nodo) is not None,
                    "usar": not err and nodo not in t.get("off", []) and respondidas.get(nodo) is None, "error": err or None})
    return out


def a_prefill(campo: Dict[str, Any]) -> Dict[str, Any]:
    """Valor que se guarda en state['pre'] para cuando el chat llegue a la pregunta."""
    nodo, v = campo["nodeId"], str(campo["valor"]).strip()
    if nodo == "P13":
        code = next((c for w, c in PROV.items() if w in v.lower()), None)
        return {"v": code or f"OTRO:{v}", "label": v}
    if nodo == "P15":
        n = re.sub(r"[^\d.]", "", v)
        return {"v": n if n in ("300", "500", "1000") else f"OTRO:{n}", "label": f"{n} Mbps"}
    return {"v": v, "label": v}
```

**`app/chat/sim/flow.py`**: salidas para no inventar datos.
```python
# P01b
push({"id": "P01b", "b": "A", "kind": "text", "text": "¿Cuál es el RUC?", "sug": ["No lo tengo ahora"], ...})
# P04
push({"id": "P04", "b": "A", "kind": "text", "text": "¿Quién es el encargado del local? (nombre y cargo)",
      "sug": ["No está en el local"], ...})
```

**`app/chat/sim/engine.py`**

1. `_parse` de texto, al inicio:
```python
NO_SE = re.compile(r"^(no\s*s[eé]|no\s*lo\s*s[eé]|no\s*(lo\s*)?tengo|no\s*sabe|no\s*hay|desconozco)(?=[\s.,!]|$)", re.I)
POR_CONFIRMAR = {"P01b", "P04"}
...
if kind == "text":
    if n["id"] in POR_CONFIRMAR and (text in ("No lo tengo ahora", "No está en el local") or NO_SE.match(text)):
        return {"v": "", "label": "Por confirmar"}
    # (sigue igual: Saltar / Continuar sin enlace / validación)
```
2. `_parse` de opciones: antes de `raise StepError("Elige una de las opciones.")`:
```python
o = match_option(n, text)
if o is not None:
    return {"v": o["v"], "label": self._opt_label(o)}
```
```python
def _n(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn").strip()

def match_option(n, text):
    t, opts = _n(text), [o for o in n["opts"] if not o.get("otro")]
    if NO_SE.match(text):
        return next((o for o in n["opts"] if re.search(r"no s[eé]|saltar|omitir", o["l"], re.I)), None)
    hit = [o for o in opts if _n(o["l"]) == t or str(o["v"]).lower() == t]
    try:
        k = float(text.replace(",", "."))
        hit = hit or [o for o in opts if o["v"] == k or o["l"].split(" ")[0] == text]
    except ValueError:
        pass
    hit = hit or [o for o in opts if t and t in _n(o["l"])]
    return hit[0] if len(hit) == 1 else None
```
   Un número que no es opción y el nodo tiene «Otro» numérico: el cliente envía `OTRO:<n>` (ya soportado).
   Una pregunta que termina en «?» no se envía a `/chat/answer`: la app la manda a **Ayuda**.

3. Respuestas pendientes de un adjunto (`state["pre"]`):
```python
def apply_prefill(self) -> List[str]:
    """Responde en orden las preguntas que ya tienen dato del adjunto. Se detiene en la primera que no valida."""
    pre = self.state.setdefault("pre", {})
    used: List[str] = []
    for _ in range(40):
        n = self.current()
        if not n or n["id"] not in pre:
            break
        c = pre.pop(n["id"])
        if self.A.get(n["id"]) is not None:
            continue
        try:
            val = self._parse(n, str(c["v"]))
        except StepError:
            break
        val["src"] = "adjunto"
        self.state["order"].append({"t": "ans", "id": n["id"], "val": val})
        self.replay()
        used.append(n["id"])
    return used
```
   Llamarlo al final de `SimChat.answer`, `amend` y `edit`, antes de `_respond`, para que las preguntas siguientes se respondan solas al llegar.
   En `node_prompt` agregar `"attachHint": adjunto.POR_NODO.get(n["id"])` y `"fromAttachment": True` en las respuestas con `src == "adjunto"`.

4. `percent()`: avance sobre el total estimado (bloqueo 2.6):
```python
def percent(self) -> int:
    c = self.counts()
    return min(99, jsround(100 * (c["qa"] + c["ea"]) / max(c["q"] + c["e"], 1)))
```

**`app/chat/sim/rules.py` · `gen_pasos`**: datos por confirmar.
```python
pc = [t for k, t in (("P01b", "el RUC"), ("P04", "el nombre y cargo del encargado del local"))
      if (a.get(k) or {}).get("label") == "Por confirmar"]
if pc:
    P.append({"p": "Cliente", "t": f"Enviar {' y '.join(pc)} para completar la minuta."})
```
(`gen_pasos(X, R, a)` ya recibe `a`: usar `a` en lugar de `A`.)

**`app/chat/router.py`**: dos rutas.
```python
class AdjuntoRequest(BaseModel):
    evaluationId: str
    state: str
    tipo: Optional[str] = None          # ruc | comp | recibo | tarjeta | frontis (si el usuario lo eligió)
    imagesBase64: List[str] = []

class AdjuntoUsarRequest(BaseModel):
    evaluationId: str
    state: str
    campos: List[Dict[str, Any]]        # filas marcadas, con el valor ya corregido por el usuario

@router.post("/adjunto")
def leer_adjunto(req: AdjuntoRequest) -> Dict[str, Any]:
    s = Session(json.loads(req.state))
    r = adjunto.leer(req.tipo, req.imagesBase64)
    if r["status"] != "OK" or not r["tipo"]:
        return {"status": r["status"] if r["status"] != "OK" else "TIPO", "tipos": {k: t["l"] for k, t in adjunto.TIPOS.items()}}
    def validar(nodo, v):
        n = next((x for x in s.N if x["id"] == nodo), None) or {"id": nodo}
        return n["valid"](v) if n.get("valid") else (flow._valid_ruc(v) if nodo == "P01b" else "")
    return {"status": "OK", "tipo": r["tipo"], "titulo": adjunto.TIPOS[r["tipo"]]["l"],
            "nota": adjunto.TIPOS[r["tipo"]].get("nota"), "campos": adjunto.campos(r["tipo"], r["valores"], s.A, validar)}

@router.post("/adjunto/usar", response_model=ChatResponse)
def usar_adjunto(req: AdjuntoUsarRequest) -> ChatResponse:
    s = Session(json.loads(req.state))
    pre = s.state.setdefault("pre", {})
    for c in req.campos:
        if s.A.get(c["nodeId"]) is None:
            pre[c["nodeId"]] = adjunto.a_prefill(c)
    s.apply_prefill()
    return _sim._respond(req.evaluationId, s)
```
`validar` usa `_valid_ruc`, `_valid_cel` y `_valid_mail` de `flow.py`. El nodo puede no existir todavía, porque se arma cuando se responde el anterior.

**Pruebas (`tests/test_adjunto_007.py`)**
- `P01b` con «no sé» y con «No lo tengo ahora» → `label == "Por confirmar"`, avanza a `P01c` y `gen_pasos` incluye «Enviar el RUC…».
- `P08` con «en operación» → `EN_OPERACION`; `P15` con «500» → 500; «cevichería» en `P09` → `StepError`.
- `/adjunto/usar` con P01, P01b y P01c cuando el chat está en P01 → quedan respondidas las tres y el nodo actual es P03.
- `/adjunto/usar` con RUC inválido → no se responde P01b y el nodo actual es P01b.
- `percent()` en la pregunta 4 < 15.

### 3.2 Gateway (Spring Boot) — `AsistenteRedIDBI-API-Gateway`

**`chat/ChatController.java`**
```java
/** Adjunto del cliente en el Chat IA (ficha RUC, comprobante, recibo, tarjeta, letrero): devuelve lo leído para revisar. */
@PostMapping(value = "/adjunto", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
public Map<String, Object> adjunto(@PathVariable Long evaluationId,
                                   @RequestPart("files") List<MultipartFile> files,
                                   @RequestPart(value = "tipo", required = false) String tipo) {
    return chatService.leerAdjunto(evaluationId, files, tipo);
}

/** Usa los datos revisados: responde la pregunta actual y deja las siguientes para cuando el chat llegue. */
@PostMapping("/adjunto/usar")
public ChatResponse usarAdjunto(@PathVariable Long evaluationId, @RequestBody Map<String, Object> body) {
    return chatService.usarAdjunto(evaluationId, body);
}
```
**`chat/ChatService.java`**
- `leerAdjunto`:
  - lee el `state` guardado de la evaluación (igual que `answerChatWithPhotos`);
  - convierte los archivos a base64 (PDF: primera página como imagen; si no se puede, devolver `status: "PDF"` para que la app pida una foto);
  - llama `POST {fastapi}/chat/adjunto`;
  - guarda el archivo con `storageService` como **evidencia del cliente**: `evidenceCode = "DOC_CLIENTE"` y `chatScope = tipo`. No entra en el conteo de evidencias ni en el anexo de fotos.
- `usarAdjunto`: llama `POST {fastapi}/chat/adjunto/usar` con `state` y `campos`, y sigue igual que `callFastApiAndPersist` (guarda el `state` y, si terminó, persiste las respuestas).
- Límite: 3 archivos y 10 MB por archivo, como `answer-photos`.

### 3.3 Android — `AsistenteRedIDBI`

**`res/layout/fragment_technical_chat.xml`** (en `containerTextRow`, antes de `etTextInput`)
```xml
<ImageButton
    android:id="@+id/btnAttach"
    android:layout_width="44dp" android:layout_height="44dp"
    android:background="@drawable/bg_outline_button"
    android:contentDescription="Adjuntar foto o documento"
    android:src="@drawable/ic_link" app:tint="@color/primary_blue" />
```
(Usar un ícono de clip si se agrega `ic_attach`. `ic_link` existe hoy.)

**`data/remote/ChatApiService.kt`** (o el servicio del chat que ya existe)
```kotlin
@Multipart
@POST("api/evaluations/{id}/chat/adjunto")
suspend fun leerAdjunto(@Path("id") id: Long, @Part files: List<MultipartBody.Part>,
                        @Part("tipo") tipo: RequestBody?): Map<String, @JvmSuppressWildcards Any?>

@POST("api/evaluations/{id}/chat/adjunto/usar")
suspend fun usarAdjunto(@Path("id") id: Long, @Body body: Map<String, @JvmSuppressWildcards Any?>): ChatResponseDto
```

**`presentation/chat/TechnicalChatFragment.kt`**
- `btnAttach` siempre activo, salvo cuando `isSending`. Abre un `BottomSheetDialog` **«Adjuntar al Chat IA»** con:
  - «Tomar foto» (el `TakePicture` que ya se usa en evidencias);
  - «Subir archivo» (`ActivityResultContracts.GetContent()` con `"image/*"`; PDF con `OpenDocument(arrayOf("application/pdf"))`);
  - la lista de 5 tipos, con el sugerido `node.attachHint` preseleccionado.
- Si `node.attachHint != null`, agregar debajo de las opciones el chip «📎 Adjuntar …» con el texto de la tabla de la sección 3.
- Con la respuesta de `leerAdjunto`, mostrar **«Datos leídos del adjunto»**: una fila por `campos` con `CheckBox(usar)`, etiqueta y `EditText(valor)`.
  - Deshabilitada si `respondido`.
  - Error en rojo si `error`.
  - `nota` debajo.
  - Botones «Descartar» y «Usar N datos».
- «Usar N datos» → `viewModel.usarAdjunto(camposMarcados)`, que llama `usarAdjunto` y procesa el `ChatResponse` con el mismo código que `sendAnswer`.
- `status == "UNAVAILABLE"`: toast «No se pudo leer el documento; escribe el dato». `status == "TIPO"`: pedir el tipo con los 5 chips.
- En la burbuja de una respuesta con `fromAttachment`, mostrar un clip pequeño, como el micrófono del dictado.
- **Escribir en preguntas con opciones** (2.4):
  - Si `node.inputType` es de opciones y el texto termina en «?», abrir **Ayuda** con la pregunta (no se envía al chat).
  - Si no, enviarlo tal cual: la API busca la opción.
  - Si vuelve `validationError`, dejar el texto en la caja.

**`TechnicalChatViewModel.kt`**: `fun leerAdjunto(uris, tipo)` y `fun usarAdjunto(campos)`, con `isSending` mientras dura.

### 3.4 Web

El Chat IA de la web consume las mismas rutas del gateway (`/chat/adjunto`, `/chat/adjunto/usar`):
- clip junto al micrófono, atajo debajo de la pregunta y la misma hoja de revisión;
- caja de texto activa también en preguntas con opciones (2.4);
- **Notificaciones del técnico** (2.5): lista de sus minutas («Tu minuta de …») sin Validar/Rechazar. El backend ya filtra por rol; el cliente web no debe mostrar acciones de validación si el rol es técnico;
- tableros: «No se pudo cargar» en vez de datos de ejemplo (R6).

---

## 4. Cómo probar (con API y gateway desplegados)

1. **Técnico › Nueva evaluación**:
   - en P01 toca «Adjuntar ficha RUC o comprobante» y sube una ficha RUC;
   - revisa: razón social, RUC y nombre marcados; dirección desmarcada;
   - «Usar 3 datos» → el chat queda en la dirección.
2. En P04 toca «No está en el local». En la vista previa: Encargado «Por confirmar» y, en Pasos a seguir del cliente, «Enviar el nombre y cargo del encargado…».
3. En P08 escribe «en operación» → se elige la opción. En P09 escribe «¿qué es retail?» → se abre Ayuda.
4. En P13 adjunta un recibo de Movistar 500 Mbps → P13 y P15 se responden.
5. La barra de avance en la pregunta 4 debe marcar menos de 15 %.
6. En P15 toca «No lo sé ahora» y en P17 elige «Otro» y escribe «a veces en la noche»:
   - P17 cuenta como Sí;
   - el plan queda «Por confirmar», con el aviso «Plan de internet por confirmar» y sin la observación «no llega a lo contratado»;
   - al terminar aparece «Quedan por confirmar: la velocidad del plan de internet» y el paso del cliente «Confirmar con ID: …».
7. **Técnico en la web › Notificaciones** → solo sus minutas, sin Validar/Rechazar. **Supervisor** → sigue igual, con Validar/Rechazar de su equipo.
8. Regresión: `pytest` en la API (golden del simulador + `test_adjunto_007.py`), `./mvnw test` y `./gradlew assembleDebug`.

El simulador 0.0.7 (`docs/simulador/simulador.html`) ya tiene todo esto para comparar el comportamiento esperado.
