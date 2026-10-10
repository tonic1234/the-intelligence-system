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

Lo medí con tiktoken: 20 documentos, 9.999 palabras, 17.522 tokens y 47 fragmentos, con el chunking de 600
tokens y 100 de solapamiento. El documento más corto tiene 363 tokens. Qué es real y qué no lo aclaro en
[`data/README.md`](data/README.md).

## Qué falta

Hoy el repo trae la configuración y el corpus. Me falta subir la recuperación híbrida, el cliente
multi-proveedor, los agentes con el supervisor, el grafo con checkpointer y aprobación humana, la API con
el worker y la cola, y las trazas. Cuando esté la API agrego el arranque con un solo comando y la tabla de
las cinco corridas con costo y latencia.

Lo dejo dicho acá y no como sorpresa: el repo todavía no se levanta, porque todavía no hay punto de
entrada. Prefiero que se lea así a que parezca que falta algo. Me tocó entregar cosas incompletas sin
decirlo y no pienso repetirlo.

## Requisitos

- **Python 3.12+**
- **Redis**, para la cola y los checkpoints del grafo
- **Docker**, si preferís no instalar Redis ni Phoenix a mano
- Una clave de modelo: Gemini (tiene capa gratis), OpenAI o Anthropic. Se elige con `LLM_PROVIDER`

Sin clave de Pinecone el recuperador arranca en modo léxico y el sistema funciona igual. Las claves no
entran al repo: se copia `.env.example` a `.env` y se completan ahí.

## Configuración

Una devolución anterior me marcó algo que me quedó: no degradar en silencio. Si el entorno no alcanza, el
sistema dice qué falta y de dónde sacarlo, en vez de explotar tres capas más adentro. Por ejemplo, con
`LLM_PROVIDER=gemini` y sin la clave:

```
falta GOOGLE_API_KEY: es la clave de gemini, que es el proveedor elegido en LLM_PROVIDER.
Se saca en https://aistudio.google.com/apikey (tiene capa gratis).
Si querés usar otro proveedor, cambiá LLM_PROVIDER (válidos: anthropic, gemini, openai).
```

## Pruebas

```bash
python -m pytest tests -q
```

Las pruebas las corrí sin claves y sin red a propósito. Donde habría una llamada al modelo o a la nube hay
un doble, así cualquiera clona el repo y verifica que funciona sin pedir prestada una API key. Me parece
importante que se puedan correr sin depender de que yo tenga una clave a mano.
