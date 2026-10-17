# The Intelligence System

Sistema de IA que responde consultas complejas sobre el derecho laboral uruguayo y sobre las políticas
internas de una empresa. Arma un equipo de agentes, los coordina con un supervisor y deja trazado todo lo
que pasa adentro.

Es el trabajo final del curso **AI Engineering** de Coderhouse. Lo armé juntando lo que hicimos módulo a
módulo: cliente multi-proveedor, cadenas, RAG, agentes, multi-agente con supervisor, API de producción con
cola y observabilidad.

## Qué hace

Le hacés una pregunta y el sistema arma un equipo para contestarla bien. Por ejemplo: "¿cuántos días de
licencia le corresponden a Ana Ferreira y cuánto cobra de salario vacacional?". Uno de los agentes busca en
las leyes y en los manuales de la empresa, otro hace las cuentas, un supervisor reparte el trabajo y valida
el resultado. La respuesta sale citando de dónde salió cada dato.

Si la tarea implica ejecutar algo con efecto real, el sistema se detiene y espera a que una persona
apruebe. Decidí que esa pausa no la dispare el modelo sino el código, así es auditable y repetible.

## Por qué elegí este tema

Me interesaba un dominio donde el sistema no pueda inventar. Con leyes y manuales internos, una respuesta
sin la cita al artículo no sirve, así que me obliga a que el RAG y las fuentes sean parte del resultado y
no un adorno. Además es un tema que conozco: trabajo con equipos y me toca ver consultas de licencias todo
el tiempo. Tuve que leer varias leyes para escribir el corpus, y me sirvió para darme cuenta de que el
error más común no es no saber, sino contestar de memoria.

## Cómo está armado

```mermaid
flowchart TD
    Cliente["Cliente (curl, una interfaz, un proceso)"] -->|"POST /tareas"| API

    subgraph Procesos["Tres procesos que solo se comunican por Redis"]
        API["API (FastAPI, async)<br/>encola y responde 202 con job_id"]
        Redis[("Redis<br/>cola + estado de los trabajos<br/>+ checkpoints del grafo")]
        Worker["Worker (proceso aparte)<br/>saca de la cola y corre el grafo"]
    end

    API --> Redis
    Redis --> Worker
    Worker --> Grafo

    subgraph Grafo["Grafo de agentes (LangGraph)"]
        Supervisor["Supervisor<br/>decide a quién delegar"]
        Aprobacion{"Nodo de aprobación<br/>¿hace falta un humano?"}
        Invest["Investigador<br/>busca en leyes y manuales"]
        Analista["Analista<br/>cuentas y cálculos"]
        Validador["Validador<br/>chequea contra lo pedido"]
        Sintesis["Síntesis<br/>respuesta final con fuentes"]
        Supervisor --> Aprobacion
        Aprobacion -->|"acción con efecto"| Humano(["Aprobación humana<br/>pausa y reanuda"])
        Aprobacion --> Invest
        Aprobacion --> Analista
        Invest --> Supervisor
        Analista --> Supervisor
        Supervisor --> Validador
        Validador -->|"falta algo"| Supervisor
        Validador --> Sintesis
    end

    Humano -.->|"POST /tareas/id/aprobar"| API

    subgraph Conocimiento["Corpus (RAG)"]
        Leyes["data/leyes/<br/>8 normas uruguayas verificadas"]
        Empresa["data/empresa/<br/>manuales de la empresa ficticia"]
        Legajos["data/legajos/<br/>datos de las personas"]
    end
    Invest --> Conocimiento

    Grafo --> Trazas["Arize Phoenix<br/>cada nodo, costo y latencia"]
```

Para leer el dibujo: el cliente nunca espera, porque la API solo encola y contesta en milisegundos. El
trabajo pesado lo hace el worker, que es otro proceso. El estado vive en Redis. Gracias a eso un trabajo
puede pausarse para pedir aprobación y reanudarse después, aunque el servidor se haya reiniciado en el
medio. Cada nodo del grafo deja su traza en Phoenix.

El detalle de cada capa, con el porqué de cada decisión, está en
[`docs/arquitectura.md`](docs/arquitectura.md).

## De dónde saca las respuestas

El sistema no contesta de memoria, busca en documentos. Los armé en tres capas separadas a propósito,
porque tiene que poder distinguir lo que dice la ley de lo que decidió la empresa. Las fichas de leyes las
verifiqué una por una contra IMPO, MTSS y BPS: no me quise confiar de la memoria para ninguna cifra.

| Capa | Qué tiene | Real o inventado |
|---|---|---|
| `data/leyes/` | Ocho fichas de normas uruguayas (licencia, salario vacacional, aguinaldo, licencias especiales, jornada y horas extras, feriados, teletrabajo, desvinculación y seguro de paro). Cada una con el artículo y el link oficial | Real, verificado contra IMPO, MTSS y BPS |
| `data/empresa/` | Reglamento interno, política de licencias, teletrabajo, seguridad de la información y onboarding de Nordika S.A. | Inventado (empresa ficticia) |
| `data/legajos/` | Seis legajos de personas de esa empresa, con antigüedad, sueldo y situación de licencias | Inventado |

Lo medí con tiktoken: 20 documentos, 19.409 tokens y 54 fragmentos, con el chunking de 600 tokens y 100
de solapamiento. El documento más corto tiene 645 tokens, así que ninguno queda por debajo del umbral y
todos se parten en más de un fragmento. Qué es real y qué no lo aclaro en
[`data/README.md`](data/README.md).

## Cómo se corre

Desde cero son dos comandos (el segundo levanta todo):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt    # base + lo que necesitan las pruebas
cp .env.example .env                   # y completá la clave del modelo

./run.sh                               # levanta Redis (si hace falta), Phoenix, la API y el worker
```

Los requisitos están partidos en dos a propósito, y el motivo viene de una devolución: el camino base
tiene que instalarse rápido y sin torch, porque el corrector quiere correr las pruebas sin esperar. Los
embeddings locales (que traen `torch`, cientos de megas) van en `requirements-embeddings.txt` y sólo
hacen falta para la búsqueda vectorial local. Medido en un entorno virtual vacío, de cero:
**78,6 segundos** el camino base y **79,6 segundos** el que necesitan las pruebas.

Al final imprime las dos URLs (API en `localhost:8000`, dashboard de trazas en `localhost:6006`) y
confirma que Redis contesta. Para bajar todo: `./run.sh --parar`. Los registros quedan en `logs/`.

Si el paquete de Phoenix no está instalado (no es requisito del camino base), `run.sh` levanta el
dashboard con la misma imagen de Docker que usa el compose, y espera a que conteste antes de arrancar la
API y el worker: Phoenix tarda unos 40 segundos y, si arrancan antes, las primeras trazas se pierden.

Con Docker es igual de corto y no hace falta tener nada instalado, sólo Docker:

```bash
docker compose up --build
```

Y si preferís verlo por partes, son dos procesos que van en dos terminales:

```bash
export PYTHONPATH=src                      # el código vive en src/
export REDIS_URL=redis://127.0.0.1:6379/0

uvicorn intelligence.main:app --port 8000  # terminal 1: la API
python -m intelligence.worker              # terminal 2: el worker
```

Los dos procesos validan el entorno al arrancar y dejan en el log en qué modo quedaron:

```
INFO arrancando: proveedor=gemini modelo=gemini-flash-latest recuperacion=hibrido trazas=activas concurrencia=2
```

Se encola una consulta así:

```bash
curl -s -X POST localhost:8000/tareas -H 'content-type: application/json' \
  -d '{"pregunta":"¿Cuántos días de licencia le corresponden a Ana Ferreira, que entró en 2016, y cuánto cobra de salario vacacional por esos días?"}'
# {"job_id":"b685e9ddee6a","estado":"pendiente"}          <- contesta en 27 ms
```

Con el worker corriendo, esa consulta terminó así (es la salida real de la corrida, no un ejemplo escrito
a mano):

```
estado: done | pasos: 2 | contribuciones: investigador, analista

A Ana Ferreira le corresponden 22 días de licencia anual (20 días base + 2 por complemento de
antigüedad), de acuerdo con los registros de su legajo. Ya gozó 10 días durante el cierre colectivo
de enero, quedándole un saldo de 12 días.

El salario vacacional equivale al 100 % del jornal líquido ($ 4.010 por día):
  - por el total generado (22 días): $ 88.220
  - por los 12 días pendientes:      $ 48.120
```

## La pausa por aprobación: cómo se decide

En la devolución de la pre-entrega 7 me marcaron que la regla que dispara la pausa estaba escrita a lo
bruto: buscaba **fragmentos** de verbo dentro del texto, así que "¿qué dice la política de vacaciones
**actualizada**?" o "resumí el **archivo** de onboarding" pausaban el trabajo y dejaban a una persona
esperando para aprobar una consulta. Lo arreglé comparando palabras completas y mirando el papel que
cumplen en la frase. La regla vive en `src/intelligence/graph/aprobacion.py` y son tres:

1. **Acción con efecto.** El pedido pide algo con consecuencias (publicar, escribir, enviar, borrar,
   firmar, pagar, transferir, desplegar, modificar, actualizar, archivar, subir, reemplazar, contratar,
   eliminar, mandar). Cuenta como acción si el verbo está en una forma de pedido ("publicá **el**
   informe") o si es un infinitivo que alguien pide ("necesito publicar", "hay que enviar"). No cuenta
   cuando viene precedido por un determinante, porque ahí la misma palabra es un sustantivo: "la
   **firma** del contrato".
2. **Costo estimado del trabajo.** Al arrancar se estima lo que va a costar el pedido: los tokens del
   pedido por las rondas esperadas del equipo, con la tabla de precios por modelo. Si llega al umbral,
   pide aprobación. Antes este número llegaba siempre vacío y la regla no se activaba nunca; ahora se
   calcula al armar el estado del trabajo y viaja con él.
3. **Gasto acumulado.** Lo que se gastó de verdad, sumado del uso que reporta el modelo en cada paso. Si
   el trabajo ya se pasó del umbral, la ronda siguiente pide aprobación.

Los dos números del costo, y el motivo de la pausa cuando la hay, se ven desde afuera:

```bash
curl -s localhost:8000/tareas/$JOB_ID | python -m json.tool | grep -E "costo|motivo"
# "motivo_aprobacion": "el pedido pide una acción con efecto ('publicar')",
# "costo_estimado": 0.000325,
# "costo_acumulado": 0.000896
```

Y la pausa por costo se puede ver sin esperar a que un trabajo la alcance solo, bajando el umbral:

```bash
UMBRAL_COSTO_APROBACION=0.0001 ./run.sh
# el trabajo queda en "esperando_aprobacion" con este motivo:
# el costo estimado del trabajo (0.0003 US$) alcanza el umbral (0.0001 US$)
```

Lo que se evalúa es el **pedido de la persona**, no la instrucción que redacta el supervisor: esa
instrucción es una descripción del trabajo ("buscá en el archivo de políticas...") y puede nombrar
acciones sin pedirlas. El supervisor tiene su propia vía, y es sólo de ida: su clasificación
estructurada (`accion_con_efectos`) puede **agregar** una pausa, nunca quitarla. La decisión dura sigue
estando en el código.

## Las cinco corridas

Lo que pide la consigna: al menos cinco pruebas del sistema con las trazas visibles. En vez de mandar
cinco veces la misma consulta, va una corrida por escenario, contra la API real, con el worker en otro
proceso y Phoenix registrando. Salida cruda de `python scripts/escenarios.py`:

| Escenario | Resultado | Tiempo | Pasos | Quién aportó |
|---|---|---|---|---|
| 1. una sola capa (consulta de ley) | `done` | 63,4 s | 1 | investigador |
| 2. dos dominios con cálculo | `done` | 75,3 s | 4 | investigador, analista, investigador, investigador |
| 3. acción con efecto, la persona aprueba | `done` | 39,1 s | 1 | investigador |
| 4. acción con efecto, la persona rechaza | `rechazado` | 6,0 s | 0 | nadie |
| 5. consulta sin cobertura del corpus | `done` | 24,3 s | 0 | nadie |

Tres cosas que muestran, y que son las que elijo mirar:

1. **La pausa funciona.** En el escenario 3 el trabajo quedó esperando aprobación con la instrucción a
   la vista y **cero pasos ejecutados**, y siguió después del OK (el escenario 4, con rechazo, cierra en
   6 segundos sin ejecutar nada).
2. **La consulta sin cobertura no se inventa nada**: *"En este momento no disponemos de los precios
   actualizados para los pasajes a Miami en enero ni de recomendaciones puntuales de hoteles (...) sin
   inventar números"*.
3. **El cálculo sale de la herramienta, no del modelo**: en el escenario 2 la respuesta trae los 21 días
   de licencia de Bruno (20 de la ley más el día que agrega Nordika a los 3 años) y el salario vacacional
   calculado con el jornal líquido de su legajo: 4.430 × 21 = **$ 93.030**.

Sobre los pasos del escenario 2: en esta corrida fueron 4 y no 2. El validador no aceptó el aporte hasta
que estuvieran citados el jornal líquido del legajo y el artículo del salario vacacional, así que el
supervisor mandó al investigador dos veces más. Esa es la defensa que dejé a propósito (un aporte sin
fuente no cuenta como trabajo hecho) y es la misma respuesta que antes: 21 días y $ 93.030.

## Las capturas y los números del dashboard

Las cuatro capturas están en [`screenshots/`](screenshots) y son del dashboard real, con el historial
limpio antes de la sesión (si no, el p95 mezcla corridas viejas):

| Captura | Qué muestra |
|---|---|
| `01-trazas.png` | Las seis trazas del proyecto (una por escenario más la del reanudado) y el panel de estadísticas con P50 y P99 |
| `02-trazas-del-grafo.png` | Los spans de las corridas sin el filtro: se ven los nodos del grafo (`supervisor`, `aprobacion`, `tras_aprobacion`, `validacion`, `ruta_tras_validacion`, `sintesis`) con su latencia y el `resume` de la aprobación |
| `03-latencia-costos.png` | La vista de métricas: el costo estimado, los percentiles de latencia (max, p50, p75, p90, p95, p99) y el consumo de tokens |
| `04-api-docs.png` | La API documentada y navegable que trae FastAPI (`/docs`), con los cuatro endpoints y sus esquemas |

Números leídos del dashboard después de las cinco corridas: **6 trazas**, **latencia P50 27,9 s** y
**P99 1m 12s** (con seis corridas el P99 es prácticamente el máximo, que fue 73,0 s), y **más de 60.000
tokens** en la sesión. En la tabla de spans cada corrida trae además su latencia, sus tokens y el costo
estimado.

Dos cosas que aclaro sobre estas métricas:

- **El costo.** La consigna pide el costo por ejecución y el dashboard lo estima solo, desde los tokens:
  en la sesión de estas corridas va de menos de un centavo (las que pausan o rechazan) a **$ 0,05** en la
  más larga. Es una estimación con el precio de lista del modelo; con la capa gratis de Gemini la factura
  del mes es cero.
- **El p95.** Con cinco corridas el p95 es prácticamente el máximo (el más lento fue 73,0 s). Por eso
  también anoto el P50 y el P99 del dashboard, que es lo que se ve en la captura de métricas.

## Lo que quedó afuera y lo que ajusté

Cuando corrí los cinco escenarios la primera vez, el escenario 1 tardaba 70,8 s y daba **cuatro pasos**:
el supervisor mandaba tres veces al analista. El analista contestaba, con razón, "falta un número: no se
especifica la cantidad de años", porque esa pregunta no pide ninguna cuenta. La culpa era del validador:
el patrón que decide si la pregunta pide una cuenta consideraba pedido de cuenta a **cualquier dígito**,
y "12.590" es el número de la ley.

Lo arreglé en el patrón (buscar las palabras que piden una cuenta, no los números sueltos) y no
aflojando el criterio, que es la defensa contra aceptar promesas como trabajo hecho. Después del
arreglo, el escenario 1 cierra en **1 paso** (63,4 s en la corrida de arriba) con la misma respuesta.
Tres pruebas de regresión cubren el caso: el número de una ley no exige al analista, una fecha tampoco,
y "cuánto cobra" o "cuántos días le corresponden" sí.

Con la capa gratis de Gemini la factura del mes es cero, pero el dashboard igual estima el costo a partir
de los tokens y del precio de lista del modelo: en esta sesión va de menos de un centavo, en las corridas
que pausan o rechazan, a **$ 0,05** en la más larga (41.698 tokens). Esa estimación no es la que decide:
la regla del umbral tiene sus propios números a la vista en la API (`costo_estimado` y `costo_acumulado`
en `GET /tareas/{id}`, ver la sección de la pausa por aprobación).


## Requisitos

- **Python 3.12+**
- **Redis**, para la cola y los checkpoints del grafo
- **Docker**, si preferís no instalar Redis ni Phoenix a mano
- Una clave de modelo: Gemini (tiene capa gratis), OpenAI o Anthropic. Se elige con `LLM_PROVIDER`

`requirements.txt` es el camino liviano: alcanza para correr la API, el worker y todas las pruebas. Los
embeddings locales (`sentence-transformers`, que trae torch) van aparte en
`requirements-embeddings.txt` y sólo hacen falta para la búsqueda vectorial contra Pinecone. Sin clave
de Pinecone el recuperador arranca en modo léxico y el sistema funciona igual. Las claves no entran al
repo: se copia `.env.example` a `.env` y se completan ahí.

## Configuración

Una devolución anterior me marcó algo que me quedó: no degradar en silencio. Si el entorno no alcanza, el
sistema dice qué falta y de dónde sacarlo, en vez de explotar tres capas más adentro. Por ejemplo, con
`LLM_PROVIDER=gemini` y sin la clave:

```
falta GOOGLE_API_KEY: es la clave de gemini, que es el proveedor elegido en LLM_PROVIDER.
Se saca en https://aistudio.google.com/apikey (tiene capa gratis).
Si querés usar otro proveedor, cambiá LLM_PROVIDER (válidos: anthropic, gemini, openai).
```

## Las pruebas (197, sin claves y sin red)

```bash
python -m pytest tests -q
```

Las pruebas las corrí sin claves y sin red a propósito. Donde habría una llamada al modelo o a la nube hay
un doble, así cualquiera clona el repo y verifica que funciona sin pedir prestada una API key. Me parece
importante que se puedan correr sin depender de que yo tenga una clave a mano.
