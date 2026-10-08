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

### Cambiado

- Esquema de datos 3: `reading`, `rating`, `supplements`, `updates` y `classification.extra`.
- Esquema de datos 2: `aliases` en los artículos. Los archivos de la versión 1 se siguen leyendo; `sb migrate` los actualiza.
- BibTeX normaliza letras matemáticas Unicode (𝑪𝑶₂ → CO2).

### Corregido

- `sb ingest RUTA` y `sb attach` ya no borran el PDF original cuando está fuera de `inbox/` (p. ej. un adjunto de Zotero): lo copian.
- Si llega el PDF original de un artículo cuyo `pdfs/KEY.pdf` es otra versión, el original la reemplaza (la otra queda en `inbox/_duplicados/`) y se quita `pdf_version_mismatch`.
