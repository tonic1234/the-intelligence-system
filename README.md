# The Intelligence System

Un sistema de IA que responde consultas complejas sobre **derecho laboral uruguayo y las políticas
internas de una empresa**, con un equipo de agentes coordinado por un supervisor, una API asíncrona y
trazabilidad completa de lo que pasa adentro.

Trabajo final del curso **AI Engineering** (Coderhouse). Une todo lo del curso: cliente multi-proveedor,
cadenas, RAG, agentes, multi-agente con supervisor, API de producción con cola y observabilidad.

---

## El sistema en una línea

Entra una pregunta ("¿cuántos días de licencia le corresponden a Ana Ferreira y cuánto cobra de salario
vacacional?"), un equipo de agentes la trabaja —uno busca en las leyes y los manuales, otro hace las
cuentas—, un supervisor reparte el trabajo y valida el resultado, y la respuesta sale **con las fuentes
citadas**. Si la tarea implica ejecutar algo con efecto, el sistema **frena y pide aprobación humana**.

## Arquitectura

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

**Cómo leer el dibujo:** el cliente nunca espera (la API solo encola y contesta en milisegundos); el
trabajo pesado lo hace el worker en otro proceso; el estado vive en Redis, y por eso un trabajo puede
pausarse para pedir aprobación y **reanudarse después, incluso si el servidor se reinició en el medio**.
Cada nodo del grafo deja su traza en Phoenix.

El detalle de cada capa, con las decisiones y el porqué de cada una, está en
[`docs/arquitectura.md`](docs/arquitectura.md).

## El corpus de conocimiento

El sistema no responde de memoria: busca en documentos. Está armado en tres capas separadas a propósito,
porque tiene que poder distinguir **lo que dice la ley** de **lo que decidió la empresa**:

| Capa | Qué contiene | Real o inventado |
|---|---|---|
| `data/leyes/` | 8 fichas de normas uruguayas (licencia, salario vacacional, aguinaldo, licencias especiales, jornada y horas extras, feriados, teletrabajo, desvinculación y seguro de paro), cada una con el artículo y el link oficial | **Real**, verificado contra IMPO, MTSS y BPS |
| `data/empresa/` | Reglamento interno, política de licencias, teletrabajo, seguridad de la información y onboarding de **Nordika S.A.** | **Inventado** (empresa ficticia) |
| `data/legajos/` | Seis legajos de personas de esa empresa, con antigüedad, sueldo y situación de licencias | **Inventado** |

Medición del corpus: **20 documentos · 9.999 palabras · 17.522 tokens · 47 fragmentos** con un chunking de
600 tokens y 100 de solapamiento. El documento más corto tiene 363 tokens.

El detalle de qué es real y qué no está en [`data/README.md`](data/README.md).

## Estado del proyecto

| Pieza | Estado |
|---|---|
| Estructura del proyecto y capa de configuración (validación del entorno al arrancar, 7 pruebas) | ✅ |
| Corpus de conocimiento en tres capas | ✅ |
| Recuperación híbrida (BM25 + vectorial) con metadatos | ⬜ |
| Cliente de LLM multi-proveedor | ⬜ |
| Agentes especialistas y supervisor | ⬜ |
| Grafo con checkpointer y aprobación humana | ⬜ |
| API asíncrona, worker y cola en Redis | ⬜ |
| Observabilidad con Phoenix | ⬜ |
| Cinco pruebas del sistema con capturas y tabla de costo/latencia | ⬜ |
| Levantar todo con una sola instrucción (Docker Compose y `run.sh`) | ⬜ |

Hoy el repo trae el corpus y la configuración. **Todavía no hay punto de entrada**: el arranque con un
solo comando se agrega junto con la API y el worker, y esta tabla se actualiza en el mismo commit.

## Requisitos

- **Python 3.12+**
- **Redis** (la cola y los checkpoints del grafo)
- **Docker** (opcional: para levantar Redis y Phoenix sin instalarlos)
- Una clave de modelo: Gemini (capa gratis), OpenAI o Anthropic — el sistema elige con `LLM_PROVIDER`

Sin clave de Pinecone el recuperador arranca en **modo léxico** y el sistema funciona igual. Las claves
nunca entran al repo: se copia `.env.example` a `.env` y se completan ahí.

## Configuración

El sistema valida el entorno **al arrancar** y, si falta algo, dice exactamente qué falta y de dónde
sacarlo. Por ejemplo, si `LLM_PROVIDER=gemini` y no está la clave:

```
falta GOOGLE_API_KEY: es la clave de gemini, que es el proveedor elegido en LLM_PROVIDER.
Se saca en https://aistudio.google.com/apikey (tiene capa gratis).
Si querés usar otro proveedor, cambiá LLM_PROVIDER (válidos: anthropic, gemini, openai).
```

Es a propósito: degradar en silencio esconde errores, y un sistema que arranca mal avisado es peor que
uno que no arranca.

## Pruebas

```bash
python -m pytest tests -q
```

Las pruebas corren **sin claves y sin red**: donde habría una llamada al modelo o a la nube hay un doble.
