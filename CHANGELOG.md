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
