# Formato de datos

Este documento es el **contrato** entre el código y los datos de una biblioteca. La implementación vive en `src/second_brain/models.py` (archivos de `library/`), `config.py` (`config.toml`) y `machines.py` (`machines/*.toml`). Todo cambio en esos módulos actualiza este documento en el mismo commit.

Versión del esquema: **4** (la 2 agregó `aliases`; la 3, `reading`, `rating`, `supplements`, `updates` y `classification.extra`; la 4, `genre`, `suggested` y `provenance.metadata`). Los archivos de versiones anteriores se siguen leyendo; `sb migrate` los actualiza.

## Reglas generales

- Texto en UTF-8 y saltos de línea LF.
- Cada archivo de `library/` es Markdown con un bloque YAML inicial (*frontmatter*) entre dos líneas `---`.
- Fechas en ISO 8601 (`2026-10-04`).
- Valores ausentes como `null`; listas vacías como `[]`.
- Serialización determinista: los campos siempre salen en el orden de esta especificación, y los textos de varias líneas en bloque (`|-`). Leer y volver a escribir un archivo no lo cambia.
- Los campos desconocidos son un error: protegen contra errores de dedo al editar a mano.
- Si un archivo tiene una `schema_version` mayor que la que entiende el código, `sb` se niega a usarlo y pide actualizar (`git pull && uv sync`).

## Estructura de una biblioteca

| Ruta | En git | Contenido |
|---|---|---|
| `config.toml` | sí | Configuración compartida |
| `machines/{nombre}.toml` | sí | Un perfil por computadora |
| `library/papers/{citekey}.md` | sí | Metadatos + resumen |
| `library/fulltext/{citekey}.md` | sí | Texto completo con marcas de página |
| `library/figures/{citekey}.md` | sí | Descripción de figuras |
| `library/notes/{citekey}.md` | sí | Notas del usuario (el programa no las toca) |
| `library/projects/{slug}.md` | sí | Proyectos |
| `inbox/` | solo `.gitkeep` | PDFs por ingerir |
| `pdfs/` | solo `.gitkeep` | PDFs ingeridos (`{citekey}.pdf`), locales |
| `.githooks/pre-commit` | sí | Ejecuta `sb check --fast` |
| `.env` | no | Secretos (`.env.example` sí va en git) |
| `.cache/` | no | Derivados: índice, caché HTTP (`http/`), último intento de descarga por DOI (`fetch.json`) |

## Identificadores

- **citekey** y **slug**: minúsculas ASCII, dígitos y guiones, sin guion al inicio ni al final (`^[a-z0-9]+(-[a-z0-9]+)*$`). El nombre del archivo debe ser igual al identificador. Un citekey no cambia nunca una vez asignado.
- **DOI**: se guarda tal como lo reporta Crossref y se compara normalizado (minúsculas, sin `https://doi.org/` ni `doi:`, `%2F` → `/`). No puede haber dos artículos con el mismo DOI normalizado.

## `library/papers/{citekey}.md`

| Campo | Tipo | Notas |
|---|---|---|
| `schema_version` | entero | `1` |
| `citekey` | texto | Ver identificadores |
| `type` | texto | Tipo CSL: `article-journal`, `paper-conference`, `chapter`, `book`, `thesis`, `report`…, y `preprint` (Crossref `posted-content`; su servidor, p. ej. SSRN, va en `container_title`). `sb bib` exporta los preprints como `@misc` con `howpublished` |
| `genre` | texto o null | Grado de una tesis: `phd`, `masters`, `bachelors`. `sb bib` exporta `@phdthesis` o `@mastersthesis` (en BibLaTeX, `@thesis` con `type = phdthesis`/`mathesis`); una de licenciatura lleva `type = {Tesis de licenciatura}`. Sin grado, una tesis sale como doctoral |
| `doi` | texto o null | |
| `ids` | mapa | `arxiv`, `isbn`, `openalex` (texto o null) |
| `aliases` | lista de texto | Otras claves con las que tus `.tex` citan este artículo (de `sb import bib`). `sb bib` también escribe la entrada con cada alias. Únicos en la biblioteca y distintos de cualquier citekey |
| `title` | texto | Obligatorio |
| `authors` | lista | Cada autor: `family` (obligatorio), `given`, `orcid` |
| `year` | entero o null | |
| `container_title`, `volume`, `issue`, `pages`, `publisher`, `language`, `license` | texto o null | `volume`, `issue` y `pages` son texto (`"110987"`, `"12-18"`) |
| `abstract` | texto o null | |
| `keywords`, `tags` | lista de texto | `tags` son etiquetas libres del usuario |
| `classification` | mapa | Ver abajo |
| `projects` | mapa `slug → {added, note}` | Cada slug debe existir en `library/projects/` |
| `pdf` | mapa o null | `sha256`, `pages`, `size_bytes`, `source` (`inbox`, `openaccess`, `institutional`), `original_filename` |
| `supplements` | lista | Material suplementario: `id` (`s1`, `s2`…), `label`, `sha256`, `pages`, `size_bytes`, `original_filename`. Texto en `library/supplements/KEY--sN.md`, PDF en `pdfs/KEY--sN.pdf` |
| `figures` | entero | Número de figuras descritas |
| `status` | texto | `awaiting_pdf`, `needs_review`, `needs_processing`, `processed` |
| `flags` | lista | `doi_uncertain`, `metadata_mismatch`, `ocr`, `possible_duplicate`, `pdf_version_mismatch`, `retracted` |
| `added` | fecha | Obligatorio |
| `reading` | texto o null | `por-leer`, `leyendo`, `leido`; null = sin marcar, que al filtrar cuenta como `por-leer` |
| `rating` | entero o null | 1 a 5 |
| `updates` | lista | Notas de Crossref sobre la obra: `type` (`retraction`, `correction`, `expression_of_concern`…), `doi`, `date`, `source` |
| `suggested` | mapa o null | Metadatos que `sb process` leyó con el LLM en las primeras páginas de un PDF sin DOI, sin confirmar: `title`, `authors`, `year`, `type`, `genre`, `container_title`, `publisher`, `doi`, `isbn`. `sb edit --accept` los aplica; se borran cuando el registro se revisa |
| `provenance` | mapa | `metadata_source` (`crossref`, `datacite`, `bib`, `bib+crossref`, `bib+datacite`, `pdf`, `manual`, `llm`), `extractor`, `fulltext_sha256`, y la procedencia del LLM (`backend`, `model`, `prompt`, `machine`, `date`, `sha256`) de `process`, `classification`, `figures` y `metadata` (la sugerencia) |

El cuerpo contiene el resumen, con las secciones *En una frase*, *Problema y objetivo*, *Datos y métodos*, *Resultados principales*, *Conclusiones* y *Limitaciones (según los autores)*.

### `classification`

| Campo | Tipo | Notas |
|---|---|---|
| `study_type` | texto o null | Debe estar en `[vocab].study_type` de `config.toml` |
| `locations` | lista | Cada sitio: `country` (ISO 3166-1 alfa-2, mayúsculas), `region` (estado o provincia), `locality` (ciudad, municipio o sitio), `page`. Todos opcionales: se llena lo que diga el artículo |
| `extra` | mapa | Campos definidos en `config.toml` → `[classification.<nombre>]`: un valor, una lista (`multiple = true`) o null |
| `reviewed` | booleano | `true` cuando el usuario confirmó la clasificación |

## `library/projects/{slug}.md`

| Campo | Tipo | Notas |
|---|---|---|
| `schema_version` | entero | `1` |
| `slug` | texto | Ver identificadores |
| `name` | texto | Obligatorio |
| `kind` | texto o null | Debe estar en `[vocab].project_kind` |
| `status` | texto | `active`, `paused`, `archived` |
| `created` | fecha | |

El cuerpo es la descripción del proyecto: el LLM la usa para sugerir qué artículos le corresponden.

## `library/fulltext/{citekey}.md`

Campos: `citekey`, `source_pdf_sha256`, `extractor`, `extracted` (fecha), `pages`, `ocr` (booleano). El cuerpo es el texto en Markdown, con una marca `<!-- page N -->` al inicio de cada página.

## `library/figures/{citekey}.md`

Campos: `citekey`, `figures` (lista de `{id, page, kind}`; `kind` es uno de `line-chart`, `bar-chart`, `scatter`, `map`, `diagram`, `photo`, `table-image`, `schematic`, `other`) y `provenance` (procedencia del LLM). El cuerpo tiene una sección por figura:

```markdown
## Fig. 3 (p. 5)
**Pie:** Indoor air temperature for cases A and B during July.

**Descripción (generada):** Gráfica de líneas…
```

En el artículo, `figures` cuenta las figuras descritas y `provenance.figures` registra el proceso. `backend: none` significa que no se encontraron pies de figura.

## `config.toml`

| Sección | Campos |
|---|---|
| `[user]` | `email` |
| `[library]` | `summary_language`, `process_prompt`, `citekey_format` |
| `[vocab]` | `study_type`, `project_kind` (listas de valores permitidos) |
| `[extract]` | `ocr_languages` (códigos de Tesseract; solo se usan los instalados) |
| `[figures]` | `describe` |
| `[access]` | `institution`, `ip_ranges` (CIDR), `vpn_hint`, `max_downloads_per_run`, `seconds_between_downloads` |
| `[classification.<nombre>]` | `label`, `description`, `values` (vacío = texto libre), `multiple` |
| `[checks]` | `max_file_mb` |

## `machines/{nombre}.toml`

| Sección | Campos |
|---|---|
| `[process]` | `backend`: `claude`, `ollama`, `anthropic` o `none` |
| `[llm]` | `provider`, `model`, `num_ctx` |
| `[chat]` | `agent`: `claude` u `opencode` |
| `[embeddings]` | `provider` (`model2vec`, `ollama` o `none`), `model` |
| `[bib_outputs]` | `slug-del-proyecto = "ruta/al/archivo.bib"` |

El perfil activo es `SB_MACHINE` o, si no está definida, el nombre local de la computadora (`scutil --get LocalHostName`) en minúsculas y con guiones.
