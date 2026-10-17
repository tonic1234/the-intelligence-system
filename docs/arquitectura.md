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
| aprobacion | Decide si la tarea implica una acción con efecto (enviar, publicar, borrar), si el costo estimado del trabajo pasa el umbral o si el gasto acumulado ya lo pasó. Si es así, pausa el grafo con `interrupt()` y espera |
| investigador | Busca en el corpus (leyes, manuales, legajos) y devuelve los fragmentos con su fuente |
| analista | Hace las cuentas: días de licencia, salario vacacional, aguinaldo, horas extras. Usa una herramienta de cálculo, no el modelo |
| validacion | Chequea la respuesta contra lo que pedía la pregunta: si faltan dominios o faltan citas, la devuelve |
| sintesis | Arma la respuesta final con las fuentes citadas |

Para que no gire en loop le puse un máximo de pasos al supervisor. Además, si el validador ve que la
rúbrica ya se cumple, fuerza el cierre. Sin eso el sistema pedía rondas de más sobre preguntas ya
resueltas, algo que me pasó en la pre-entrega anterior y que se ve en las trazas.

## La pausa por aprobación humana

La decisión de pausar no la toma el modelo, la toma el código: es auditable, repetible y se puede probar.
Son tres reglas, en `src/intelligence/graph/aprobacion.py`:

1. **Acción con efecto.** El pedido pide algo con consecuencias. El verbo tiene que estar en una forma de
   pedido: imperativo con objeto ("publicá **el** informe") o infinitivo que alguien pide ("necesito
   publicar", "hay que enviar"). Y no cuenta si viene precedido por un determinante, porque ahí la misma
   palabra es un sustantivo ("la **firma**", "el **envío**").
2. **Costo estimado del trabajo.** Al armar el estado del trabajo se estima el costo del pedido: tokens
   del pedido por las rondas esperadas del equipo, con la tabla de precios por modelo (`graph/costos.py`).
   Si llega al umbral (`UMBRAL_COSTO_APROBACION`, 0,02 US$ por defecto), pide aprobación.
3. **Gasto acumulado.** Lo gastado de verdad, sumado del uso que reporta el modelo en cada paso. Es la
   red para un trabajo que se estira: cuando el acumulado pasa el umbral, la ronda siguiente pide
   aprobación.

En la devolución de la pre-entrega 7 me marcaron dos cosas que están arregladas acá: la regla buscaba
**fragmentos** de verbo (por eso "la política actualizada" y "el archivo de onboarding" pausaban
consultas inocentes), y la comparación se hacía sobre la instrucción que redacta el supervisor además del
pedido. Ahora se evalúa el **pedido de la persona**, y el supervisor sólo puede **agregar** una pausa con
su clasificación estructurada (`accion_con_efectos`), nunca quitarla. El lado seguro del error es pausar
de más y que una persona decida, no dejar pasar una acción que nadie autorizó.

Sobre el mecanismo:

- Si la tarea no es crítica, el grafo sigue de largo sin tocar nada.
- Si lo es, `interrupt()` guarda el estado en el checkpointer y devuelve el control. El trabajo queda
  en `esperando_aprobacion` con la instrucción y el motivo a la vista, y con cero pasos ejecutados.
- Cuando la persona aprueba (`POST /tareas/{id}/aprobar`), el worker reanuda con `Command(resume=...)`
  desde el checkpoint. No vuelve a empezar y no pide permiso otra vez en las rondas siguientes.
- Si nadie contesta en `MINUTOS_ESPERA_APROBACION`, el trabajo se cierra como
  `rechazado_por_timeout`: una aprobación colgada no puede dejar el estado para siempre.

Los dos números del costo quedan guardados con el trabajo y se leen desde la API
(`GET /tareas/{id}` devuelve `costo_estimado` y `costo_acumulado`), además de verse en el dashboard.

## Instalación y arranque

Los requisitos están partidos en dos archivos por un motivo concreto: la devolución de la pre-entrega 7
decía que `pip install` "no terminó en 10 minutos" y que por eso no se pudieron correr las pruebas. El
culpable era que el camino base arrastraba `sentence-transformers` (que trae torch) y el paquete completo
de Phoenix. Hoy:

| Instalación | Qué trae | Para qué sirve | Medido en un venv vacío |
|---|---|---|---|
| `pip install -r requirements.txt` | El camino liviano, sin torch | Correr la API, el worker y todas las pruebas | 78,6 s |
| `pip install -r requirements-dev.txt` | Lo anterior más pytest, fakeredis y httpx | Correr la suite completa | 79,6 s |
| `pip install -r requirements-embeddings.txt` | `sentence-transformers` + `langchain-huggingface` | Sólo para la búsqueda vectorial local (opcional) | no la medí |

El dashboard de trazas no está en ninguno de los tres: corre en su contenedor, y `run.sh` lo levanta con
Docker si no encuentra el paquete de Python instalado.

El arranque en Docker respeta el orden: `api` y `worker` esperan a que **Redis** y **Phoenix** estén
sanos. Phoenix tiene su `healthcheck`, que es a mano porque su imagen no trae shell ni curl (arranca en
`/usr/bin/python3.13` y se pregunta a sí misma por su puerto). Medido contra la imagen real, Phoenix tarda
unos 40 segundos en contestar: sin esa espera, los dos procesos arrancaban con el colector caído y las
primeras trazas se perdían, que es exactamente lo que la devolución marcó.

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
| Los requisitos pesados van en un archivo aparte | Instalar torch en el camino crítico hacía que la instalación no terminara en 10 minutos (devolución de la pre-entrega 7) |
| El precio del modelo sale de una tabla y no de una suposición | Inventar un precio es peor que decir que no hay: con un modelo sin precio, la estimación da cero y lo deja dicho en el log |
| El costo estimado se calcula por pedido, al armar el estado | Tenerlo como parámetro del ejecutor hacía que llegara siempre vacío y que la regla del umbral no se activara nunca |
| La pausa se evalúa sobre el pedido de la persona, no sobre la instrucción del supervisor | La instrucción describe el trabajo y puede nombrar acciones sin pedirlas; el pedido es el que tiene el efecto |
