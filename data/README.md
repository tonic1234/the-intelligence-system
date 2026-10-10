# El corpus de conocimiento de este sistema

Acá vive lo que el sistema sabe. Está armado en dos capas a propósito, porque el sistema tiene que
distinguir **lo que dice la ley** de **lo que la empresa decidió**, y responder diciendo cuál de las
dos está aplicando.

```
data/
├── leyes/      → normas uruguayas reales, con el artículo citado y la fuente oficial
├── empresa/    → los documentos internos de Nordika S.A. (empresa FICTICIA)
└── legajos/    → los datos de los empleados de esa empresa (INVENTADOS)
```

## Lo que es real y lo que es inventado (esto importa)

- **`leyes/` es real**: cada ficha resume una norma vigente de la República Oriental del Uruguay y
  al final lleva el número de ley, el artículo y el link a la fuente oficial (IMPO, MTSS o BPS).
  Ninguna cifra de estas fichas está puesta de memoria: se verificaron contra esas fuentes.
- **`empresa/` y `legajos/` son inventados**: Nordika S.A. no existe. Los nombres, los legajos, los
  sueldos y los organigramas son ficticios y están escritos para que el sistema tenga datos concretos
  con los que razonar. Cualquier parecido con una empresa real es casualidad.

El sistema nunca debe presentar una regla interna como si fuera obligación legal, ni al revés. Cuando
las dos capas hablan del mismo tema, la ficha de ley dice cuál es el **piso** y el documento de
empresa dice qué agregó Nordika por encima de ese piso (porque la empresa puede mejorar el mínimo
legal, nunca empeorarlo).

## Cómo se usa

1. `scripts/ingest.py` parte los documentos en fragmentos medidos **en tokens** (no en caracteres),
   con metadatos (`tema`, `tipo` = ley | empresa | legajo, `fuente`, `norma`).
2. Los fragmentos van al índice vectorial; sin `PINECONE_API_KEY` el mismo código corre en modo
   léxico (BM25) sobre los mismos documentos.
3. Las respuestas tienen que citar de dónde salen: el nombre del documento y, si es una ley, la norma
   y el artículo.

## Índice del corpus

| Documento | Capa | Tema |
|---|---|---|
| `leyes/01-licencia-anual.md` | ley | Licencia anual: días, antigüedad y fraccionamiento (Ley 12.590) |
| `leyes/02-salario-vacacional-y-aguinaldo.md` | ley | Salario vacacional (Ley 16.101) y aguinaldo (Ley 12.840) |
| `leyes/03-licencias-especiales.md` | ley | Estudio, matrimonio, duelo, paternidad y familiares a cargo (Ley 18.345) |
| `leyes/04-jornada-y-horas-extras.md` | ley | Jornada, recargos y tope semanal (Ley 15.996, Decreto 550/89) |
| `leyes/05-feriados.md` | ley | Feriados pagos y régimen de corrimiento (art. 18 Ley 12.590, Ley 16.805) |
| `leyes/06-teletrabajo.md` | ley | Teletrabajo y derecho a la desconexión (Ley 19.978) |
| `leyes/07-maternidad-paternidad-y-cuidados.md` | ley | Licencias y subsidios por nacimiento (Ley 19.161, Ley 11.577) |
| `leyes/08-desvinculacion-y-seguro-de-paro.md` | ley | Despido, aguinaldo proporcional y subsidio por desempleo |
| `empresa/…` | empresa | Reglamento interno y políticas de Nordika S.A. |
| `legajos/…` | legajo | Empleados de Nordika S.A. (datos ficticios, con antigüedad y sueldo) |
