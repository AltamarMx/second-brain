# Arquitectura

Para quien modifique el código. El porqué de cada decisión está en `PLAN.md` y en `docs/decisiones/`.

## Dos repositorios

- **`second-brain`** (este): el paquete `second_brain` y el comando `sb`. No contiene datos ni nada específico de una persona o institución.
- **Repositorio de datos** (p. ej., `biblioteca`): creado con `sb init`. Declara `second-brain` como dependencia por git en su `pyproject.toml` y fija la versión exacta en `uv.lock`.

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `cli.py` | Comandos `sb` (Typer). Solo interpreta argumentos e imprime; la lógica vive en los demás módulos |
| `config.py` | Localiza la biblioteca (`--home`, `SB_HOME`, búsqueda de `config.toml`), lee `config.toml` y `.env` |
| `machines.py` | Detecta la máquina activa y lee su perfil `machines/{nombre}.toml` |
| `models.py` | Esquemas pydantic de cada archivo de `library/`: el contrato de `docs/formato-datos.md` |
| `library.py` | **Única** capa que lee y escribe `library/`: frontmatter YAML determinista y escritura atómica |
| `scaffold.py` | `sb init` y `sb machine init`: plantillas de `templates/` |
| `checks.py` | `sb check`: validación de la biblioteca |
| `doctor.py` | `sb doctor` (dependencias de la máquina) y `sb status` (pendientes) |
| `ingest/pipeline.py` | `sb ingest`: orquesta los pasos y decide duplicados, re-vinculación y estado |
| `ingest/extract.py` | PDF → Markdown por página (pymupdf4llm), OCR, título aproximado |
| `ingest/doi.py` | Encontrar y normalizar DOIs e IDs de arXiv |
| `ingest/metadata.py` | Crossref y DataCite, con caché en `.cache/http/` |
| `ingest/dedupe.py` | Índice en memoria por hash, DOI y título |
| `fetch/download.py` | Descarga de PDFs: acceso abierto, acceso institucional, pausas y límites, clasificación de fallos |
| `fetch/network.py` | IP pública y rangos institucionales |
| `projects.py` | Crear proyectos, agregar y quitar artículos, listar |
| `bibtex.py` | BibTeX/BibLaTeX determinista desde los registros |
| `texcite.py` | Citekeys citados en un `.tex` |
| `processing.py` | `sb process`: resumen, clasificación y figuras; validación y procedencia |
| `backends/` | Quién procesa: `claude_cli.py` (`claude -p` con `--json-schema`); Ollama y API llegan en la fase 6 |
| `prompts/` | Prompts versionados (`process.v1.md`, `figures.v1.md`) |
| `index.py` | Índice SQLite FTS5: artículos y pasajes (texto y figuras), filtros, búsqueda con RRF |
| `agents.py` | `sb agents sync`: plantillas de `templates/agents/` hacia la biblioteca |
| `citekey.py` | Generación de citekeys |
| `reading.py` | Páginas y secciones de un texto completo |
| `textutil.py` | Normalización de texto (ASCII, etiquetas HTML, comparación difusa) |
| `mcp_server.py` | Servidor MCP (fase 6; por ahora es un marcador) |
| `templates/` | Esqueleto de un repositorio de datos |

## Reglas

1. Nada fuera de `library.py` abre archivos de `library/`.
2. Los comandos que usan los agentes aceptan `--json`.
3. Mensajes al usuario en español; código, identificadores y docstrings en inglés.
4. Un cambio de formato sube `SCHEMA_VERSION` en `models.py`, añade una migración (`sb migrate`, fase posterior) y actualiza `docs/formato-datos.md`.

## Flujo de datos (fase 0)

```text
sb init RUTA ──► templates/ ──► config.toml, .gitignore, .githooks/, carpetas con .gitkeep
sb check ──► config.py + library.py + models.py ──► lista de problemas (errores y avisos)
git commit (en la biblioteca) ──► .githooks/pre-commit ──► uv run sb check --fast
```
