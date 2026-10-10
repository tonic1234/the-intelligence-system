# Arquitectura del sistema

Acá está el detalle de cada capa: qué hace, de qué depende y por qué lo resolví así. El resumen visual
está en el [README](../README.md).

## Los tres procesos

```
   cliente ──HTTP──▶ API (FastAPI)  ──encola──▶  Redis  ──▶  Worker (proceso aparte)
                        │                          │              │
                    responde 202              estado del job    corre el grafo
                    con un job_id              + checkpoints     de agentes
```

Puse un worker aparte porque el equipo de agentes tarda entre 15 y 180 segundos. Si eso corriera dentro
del endpoint, el event loop quedaría bloqueado y el cliente esperando sin saber nada. Con el worker
separado, la API contesta en milisegundos con un `job_id` y el cliente consulta el estado cuando quiere.

El estado vive en Redis y no en memoria porque los procesos no comparten memoria. Si estuviera en un
diccionario dentro de la API, el worker no lo vería, no se podrían correr dos workers y un reinicio
perdería todo. Un detalle que aprendí a la fuerza: el estado del trabajo se guarda ANTES de encolarlo. Si
el worker gana la carrera y mira el trabajo antes de que exista el estado, el cliente queda en un polling
infinito. Ese es justamente el error que la consigna marcaba como grave.

## El grafo de agentes

```
start ─▶ supervisor ─▶ aprobacion ─┬─▶ investigador ─▶ supervisor
                                   ├─▶ analista ─────▶ supervisor
                                   ├─▶ validacion
                                   └─▶ sintesis ─▶ end
```

| Nodo | Qué hace |
|---|---|
| supervisor | Lee la pregunta y decide a quién delegar, con salida estructurada (Pydantic) y un tope de pasos como corte duro |
| aprobacion | Decide si la tarea implica una acción con efecto (enviar, publicar, borrar) o supera un umbral de costo. Si es así, pausa el grafo con `interrupt()` y espera |
| investigador | Busca en el corpus (leyes, manuales, legajos) y devuelve los fragmentos con su fuente |
| analista | Hace las cuentas: días de licencia, salario vacacional, aguinaldo, horas extras. Usa una herramienta de cálculo, no el modelo |
| validacion | Chequea la respuesta contra lo que pedía la pregunta: si faltan dominios o faltan citas, la devuelve |
| sintesis | Arma la respuesta final con las fuentes citadas |

Para que no gire en loop le puse un máximo de pasos al supervisor. Además, si el validador ve que la
rúbrica ya se cumple, fuerza el cierre. Sin eso el sistema pedía rondas de más sobre preguntas ya
resueltas, algo que me pasó en la pre-entrega anterior y que se ve en las trazas.

## La pausa por aprobación humana

La decisión de pausar no la toma el modelo, la toma el código: mira verbos de acción en la instrucción y el
costo estimado del paso. Es auditable y repetible, y por eso se puede probar.

- Si la tarea no tiene efecto, el grafo sigue de largo.
- Si lo tiene, `interrupt()` guarda el estado en el checkpointer y devuelve el control. El trabajo queda
  en `esperando_aprobacion` con la instrucción a la vista y cero pasos ejecutados.
- Cuando la persona aprueba (`POST /tareas/{id}/aprobar`), el worker reanuda con `Command(resume=...)`
  desde el checkpoint. No vuelve a empezar y no pide permiso otra vez en las rondas siguientes.

## Las tres capas del corpus

Las separé porque el sistema tiene que poder decir de dónde sacó cada cosa. No es lo mismo una obligación
legal que una decisión de la empresa, y mezclarlas sería el peor error posible en este dominio.

| Capa | Rol |
|---|---|
| `data/leyes/` | El piso: lo que la ley obliga. Cada ficha cita norma y artículo |
| `data/empresa/` | Lo que la empresa agrega sobre ese piso. Puede mejorar, nunca empeorar |
| `data/legajos/` | Los datos de las personas, para que las preguntas tengan números con los que calcular |

Cada fragmento se indexa con metadatos (`tema`, `tipo`, `fuente`, `norma`) para que la respuesta pueda
citar y para que la búsqueda pueda filtrar por capa.

## Observabilidad

Cada nodo deja su traza en Arize Phoenix: prompt, respuesta, tokens, costo y latencia. La
instrumentación va **solo en el worker**, que es el proceso donde corre el grafo, y solo sobre
LangChain.

Lo aprendí de dos maneras, las dos en corridas reales:

- Si se instrumenta también **FastAPI**, el dashboard se llena de spans de `GET /tareas/<job_id>` (el
  polling del cliente) y las trazas de los agentes quedan enterradas. Lo medí: 387 trazas en el
  proyecto, casi todas de consultas de estado, y ni un solo span visible del supervisor sin filtrar.
- Si la **API** activa la instrumentación sólo para que el `/health` diga "trazas: true", el efecto es
  el mismo. El `/health` ahora informa otra cosa (si el sistema tiene la trazabilidad configurada), y
  la API no toca la instrumentación.

Y una práctica que ayuda a que los números signifiquen algo: **limpiar el historial de Phoenix antes de
la sesión de pruebas**. El p95 se calcula sobre todas las trazas del proyecto, así que si quedan las de
corridas viejas (o las de depuración), el número no es el de la corrida que estás midiendo.

## Decisiones que sostengo por un motivo

| Decisión | Por qué |
|---|---|
| La configuración se valida al arrancar y el mensaje dice qué falta | Degradar en silencio esconde errores. Lo pedía la devolución de la pre-entrega 4 |
| El `.env` que se lee es solo el del repo, con ruta explícita | Buscar hacia arriba con `find_dotenv` hizo que este proyecto arrancara con las claves de otra carpeta del servidor |
| Sin Pinecone el recuperador cae a modo léxico | Lo opcional tiene que ser opcional de verdad: el repo corre sin tarjeta |
| Las pruebas corren sin claves y sin red | Así cualquiera clona el repo y verifica que anda, sin pedir prestada una API key |
