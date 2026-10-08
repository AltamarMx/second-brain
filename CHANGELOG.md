# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). El programa usa versionado semántico; la versión del esquema de datos (`schema_version`) va aparte.

## [Sin publicar]

### Añadido

- Fase 0: paquete `second_brain` con el comando `sb`.
- `sb init`, `sb machine init/show`, `sb doctor`, `sb check`, `sb status`.
- Esquema de datos versión 1 (`docs/formato-datos.md`).
- CI con ruff y pytest; hooks de pre-commit locales.
- Fase 1: `sb ingest` (DOI desde metadatos y texto, validación del título en Crossref/DataCite, búsqueda por título, deduplicación por hash, DOI y título, re-vinculación de PDFs, OCR, caché HTTP), `sb show`, `sb text` (páginas y secciones) y `sb remove`.
- Configuración `[extract].ocr_languages`.
- Fase 2: `sb ingest DOI…`, `--dois`, `--retry`; registros `awaiting_pdf`; descarga por acceso abierto (arXiv, Unpaywall) e institucional (enlaces de Crossref, `citation_pdf_url`) con detección de red y aviso de VPN, pausas y límite por corrida; `sb pdf status/get/open` (con `--awaiting`).
- Fase 3: `sb project create/add/remove/list/show/archive`; `sb bib` (proyecto, citekeys, `--from-tex`, `sync`, BibTeX y BibLaTeX) con protección de mayúsculas; aviso de `sb check` para `[bib_outputs]` desconocidos.
- Fase 4: `sb process` (resumen, clasificación y figuras con `claude -p` y salida validada por esquema; procedencia; respeta ediciones a mano; `--pending`, `--stale`, `--force`) y procesamiento automático al ingerir; `sb figures`; índice FTS5 con `sb search`, `sb list`, `sb passages`, `sb index`; `AGENTS.md`, skills `sb-*`, `.claude/settings.json` con `sb agents sync` (también en `sb init`); `sb chat`.
- Fase 5: `sb import bib` (cualquier `.bib`; conserva citekeys, alias para claves no válidas como archivo, metadatos de Crossref si hay DOI); los PDFs se asocian a registros sin PDF también por título; `sb bib --all`; `sb migrate`.
- Fase 6: backends `ollama` (local) y `anthropic` (API, extra opcional); `sb ask`; servidor MCP `sb-mcp`; `opencode.json` y agente `bibliotecario`; `sb chat opencode`.
- Fase 7: búsqueda híbrida (BM25 + embeddings multilingües locales con model2vec u Ollama, fusionados con RRF) en `sb search`, `sb passages`, `sb ask` y MCP; `--mode`; `sb eval search` (recall@k y MRR).
- Fase 8: estado de lectura y calificación (`sb read`, `--reading`); notas de Crossref y retractaciones (`sb check --retractions`); grafo de citas (`sb refs`, `--missing`, `--html`, que guarda en `.cache/grafo.html` y abre el navegador); material suplementario (`sb attach`, `sb text --supplement`); campos de clasificación configurables (`[classification.*]`, `sb process --reclassify`, `--field`).
- `sb refs --html`: línea de tiempo por año de publicación (▶ y control deslizante); los artículos sin `year` quedan fijos y marcados como pendientes, y `sb refs --html` los lista.
- `AGENTS.md` de la biblioteca: lista de comandos (un test exige que estén todos los de la CLI) y comportamientos no obvios; la skill `sb-ingerir` explica cómo resolver `needs_review`.
- `sb ingest --all [--push]`: ingerir, procesar todo lo pendiente, validar y hacer commit en un solo paso.
- `sb edit KEY`: corrige metadatos (a mano o con `--from-doi`, que solo aplica lo que Crossref trae) sin tocar texto, resumen, proyectos ni lectura, y saca al artículo de `needs_review`; `--rekey`/`--key` cambian el citekey y dejan el anterior como alias.
- `sb process` propone metadatos (autores, título, año, tipo, revista, DOI, ISBN) para los artículos que entraron de un PDF sin DOI; quedan en `suggested` hasta que `sb edit KEY --accept` los aplica.
- `sb import bib` copia los PDFs del campo `file` de las exportaciones de Zotero, Better BibTeX y JabRef a sus registros, y no asocia los que no muestran el título del registro; `sb ingest PDF --key KEY` asocia un PDF a un artículo concreto.
- `sb pdf link [CARPETA…]`: coloca en `pdfs/` los PDFs que faltan en esta máquina buscándolos por sha256 (p. ej. en `~/Zotero/storage`), sin mover los originales; `sb pdf open --missing` abre también los procesados sin PDF local.
- Campo `genre` con el grado de las tesis (`phd`, `masters`, `bachelors`): `sb bib` exporta `@mastersthesis` y las de licenciatura con `type = {Tesis de licenciatura}`; `sb edit --genre`.

### Cambiado

- Esquema de datos 4: `genre` (grado de una tesis), `suggested` y `provenance.metadata` (metadatos propuestos por el LLM). Los archivos anteriores se siguen leyendo; `sb migrate` los actualiza.
- Esquema de datos 3: `reading`, `rating`, `supplements`, `updates` y `classification.extra`.
- Esquema de datos 2: `aliases` en los artículos. Los archivos de la versión 1 se siguen leyendo; `sb migrate` los actualiza.
- BibTeX normaliza letras matemáticas Unicode (𝑪𝑶₂ → CO2).
- Regla 11 de `AGENTS.md`: lista todos los prefijos de commit (`ingest:`, `process:`, `edit:`, `project:`, `agents:`; `sb ingest --all` usa `ingest/process:`).

### Corregido

- `sb ingest RUTA` y `sb attach` ya no borran el PDF original cuando está fuera de `inbox/` (p. ej. un adjunto de Zotero): lo copian.
- Si llega el PDF original de un artículo cuyo `pdfs/KEY.pdf` es otra versión, el original la reemplaza (la otra queda en `inbox/_duplicados/`) y se quita `pdf_version_mismatch`.
- El año de los PDFs sin DOI ya no sale de un ISSN, ISBN, teléfono o DOI, y prefiere el de ©, "published", la línea de cita de la revista o las fechas.
- El título de los PDFs sin DOI salta avisos de portada y encabezados de institución, corta el nombre del autor en tesis, revisa las páginas 1 a 3 y usa el título de los metadatos del PDF cuando aparece en el texto.
- Las ecuaciones de Word (p. ej. CO₂ escrito como fórmula) ya no salen como "CCCC": se repara en memoria el mapa ToUnicode de la fuente matemática y las letras matemáticas se guardan como texto plano.
- Los PDFs de SSRN se identifican por su DOI (`ssrn.com/abstract=N` → `10.2139/ssrn.N`), validado con Crossref.
- `sb import bib` ya no borra campos del .bib cuando Crossref no los trae; `--prefer-bib` hace que ganen los del .bib y Crossref solo llene huecos.
- Los preprints (Crossref `posted-content`) tienen el tipo `preprint` y se exportan como `@misc` con su servidor (`howpublished = {SSRN}`) en lugar de `@article` sin revista.
- Los nombres de autor que Crossref o DataCite dan en minúsculas se capitalizan ("liu, yongping" → "Liu, Yongping").
- Una descarga que falla porque la editorial no responde ya no dice "sin conexión con doi.org": nombra el servidor que falló y deja el artículo esperando PDF en lugar de abortar como si no hubiera red.
- `sb pdf get --json` (y `sb ingest DOI`) informan el estado real de un artículo ya registrado cuando la descarga falla, en lugar de `awaiting_pdf`.
- `sb bib` conserva subíndices y superíndices: CO₂ sale como `CO\textsubscript{2}` y m² como `m\textsuperscript{2}`, en lugar de CO2.
- Las llaves que protegen mayúsculas en BibTeX ya no incluyen la puntuación: `{IoT},` en lugar de `{IoT,}`.
- `sb list --reading por-leer` (y `sb search`) incluye los artículos sin estado de lectura, en lugar de devolver 0.
