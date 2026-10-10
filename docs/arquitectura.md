# Arquitectura del sistema

Acá está el detalle de cada capa: qué hace, de qué depende y por qué se decidió así. El resumen visual
está en el [README](../README.md).

## Los tres procesos

```
   cliente ──HTTP──▶ API (FastAPI)  ──encola──▶  Redis  ──▶  Worker (proceso aparte)
                        │                          │              │
                    responde 202              estado del job    corre el grafo
                    con un job_id              + checkpoints     de agentes
```

**Por qué un worker aparte y no todo dentro del request.** El equipo de agentes tarda entre 15 y 180
segundos: hacerlo dentro del endpoint bloquearía el event loop y el cliente quedaría esperando sin saber
nada. Con el worker separado, la API contesta en milisegundos con un `job_id` y el cliente consulta el
estado cuando quiere.

**Por qué el estado vive en Redis y no en memoria.** Porque los procesos no comparten memoria: si el
estado estuviera en un diccionario dentro de la API, el worker no lo vería, no se podrían correr dos
workers y un reinicio perdería todo. El estado del trabajo **se guarda antes de encolarlo** — si el
worker gana la carrera y mira el trabajo antes de que exista el estado, el cliente quedaría en un
polling infinito. Ese es el error que la consigna de la entrega anterior marcaba como grave.

## El grafo de agentes

```
start ─▶ supervisor ─▶ aprobacion ─┬─▶ investigador ─▶ supervisor
                                   ├─▶ analista ─────▶ supervisor
                                   ├─▶ validacion
                                   └─▶ sintesis ─▶ end
```

| Nodo | Qué hace |
|---|---|
| **supervisor** | Lee la pregunta y decide a quién delegar, con salida estructurada (Pydantic) y un tope de pasos como corte duro |
| **aprobacion** | Decide si la tarea implica una acción con efecto (enviar, publicar, borrar) o supera un umbral de costo. Si es así, pausa el grafo con `interrupt()` y espera |
| **investigador** | Busca en el corpus (leyes, manuales, legajos) y devuelve los fragmentos con su fuente |
| **analista** | Hace las cuentas: días de licencia, salario vacacional, aguinaldo, horas extras. Usa una herramienta de cálculo, no el modelo |
| **validacion** | Chequea la respuesta contra lo que pedía la pregunta (¿faltan dominios?, ¿hay citas?) |
| **sintesis** | Arma la respuesta final con las fuentes citadas |

**Anti-bucle:** el supervisor tiene un máximo de pasos, y si el validador detecta que la rúbrica ya se
cumple, fuerza el cierre. Sin eso el sistema pide rondas de más sobre preguntas ya resueltas (me pasó en
la pre-entrega anterior y se ve en las trazas).

## La pausa por aprobación humana

La decisión de pausar **no la toma el modelo**: se toma en código, mirando verbos de acción en la
instrucción y el costo estimado del paso. Es auditable y repetible, y por eso se puede probar.

- Si la tarea no tiene efecto, el grafo sigue de largo.
- Si lo tiene, `interrupt()` guarda el estado en el checkpointer y devuelve el control. El trabajo queda
  en `esperando_aprobacion` con la instrucción a la vista y **cero pasos ejecutados**.
- Cuando el humano aprueba (`POST /tareas/{id}/aprobar`), el worker reanuda con `Command(resume=...)`
  **desde el checkpoint**: no vuelve a empezar y no pide permiso otra vez en las rondas siguientes.

## Las tres capas del corpus

Están separadas porque el sistema tiene que poder decir **de dónde sacó cada cosa** y no confundir una
obligación legal con una decisión de la empresa:

| Capa | Rol |
|---|---|
| `data/leyes/` | El **piso**: lo que la ley obliga. Cada ficha cita norma y artículo. |
| `data/empresa/` | Lo que la empresa **agrega** sobre ese piso (puede mejorar, nunca empeorar). |
| `data/legajos/` | Los **datos** de las personas, para que las preguntas tengan números con los que calcular. |

Cada fragmento se indexa con metadatos (`tema`, `tipo`, `fuente`, `norma`) para que la respuesta pueda
citar y para que la búsqueda pueda filtrar por capa.

## Observabilidad

Cada nodo deja su traza en Arize Phoenix: prompt, respuesta, tokens, costo y latencia. La instrumentación
va **sólo sobre LangChain**, no sobre FastAPI: si se instrumenta todo, el dashboard se llena de spans de
`GET /tareas/<id>` (el polling del cliente) y las trazas de los agentes quedan enterradas. Ese fue un
hallazgo real de la corrida anterior y está explicado en el módulo de instrumentación.

## Decisiones que se sostienen por un motivo

| Decisión | Por qué |
|---|---|
| Configuración validada al arrancar, con mensaje que dice qué falta | Degradar en silencio esconde errores (lo pedía la devolución de la pre-entrega 4) |
| El `.env` se lee sólo el del repo, con ruta explícita | Buscar hacia arriba (`find_dotenv`) hizo que este proyecto arrancara con las claves de otra carpeta del servidor |
| Sin Pinecone, el recuperador cae a modo léxico | Lo opcional tiene que ser opcional de verdad: el repo corre sin tarjeta |
| Las pruebas corren sin claves y sin red | Así cualquiera puede clonar el repo y verificar que funciona sin pedir prestada una API key |
