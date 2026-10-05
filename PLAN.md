# PLAN — Second Brain de artículos científicos

> **Estado:** v0.5 (borrador) · **Fecha:** 2026-10-04
> Documento vivo: marca las casillas al avanzar, responde las decisiones abiertas (§15) y registra cada cambio de rumbo en la bitácora (§16).

## Resumen

Una biblioteca personal de artículos que se alimenta desde la terminal (soltando PDFs en `inbox/` o dando DOIs) y se consulta en lenguaje natural desde Claude Code u OpenCode con un LLM local. Decisiones clave:

- **Todo bajo demanda:** nada corre en segundo plano. `uv run sb ingest` ingiere sin abrir ningún agente; `uv run sb chat` abre Claude Code u OpenCode ya configurados; `uv run sb ask "…"` responde una pregunta suelta.
- **Dos repositorios:** el **código** (`second-brain`, este repo) es un paquete Python genérico que puedes compartir con otras personas; el **repo de datos** (`biblioteca`, privado) lo instala desde GitHub con `uv`. Se actualizan por separado. Nada se instala de forma global.
- **Ingesta de dos formas:** todos los PDFs de `inbox/`, o una lista de DOIs. En el segundo caso se descarga el PDF (acceso abierto o institucional) y, si falla, se pide **activar el OpenVPN de la UNAM**.
- **Fuente de verdad en texto plano** (Markdown + YAML) en `library/`, un archivo por artículo. Los PDFs no van a git, pero `inbox/` y `pdfs/` sí existen en el repositorio (vacías).
- **Cada artículo se procesa una vez:** resumen + clasificación (tipo de estudio: experimental, numérico o ambos; país, estado/provincia y localidad) + **descripción de figuras**, con el backend que elija cada máquina (en el iMac, Claude).
- **Los PDFs ingeridos se mueven a `pdfs/`:** quedan solo en la máquina local, sin respaldo y fuera de git. El texto y las figuras sí están en git, así que las demás máquinas no necesitan los PDFs.
- **Perfiles por máquina versionados** (`machines/imac-ier.toml`, `machines/mbp-m5.toml`…): cada computadora declara su modelo local, su backend de resúmenes y sus rutas. Solo los secretos quedan fuera de git (`.env`).
- **Proyectos explícitos:** se crean con `sb project create` o pidiéndoselo al agente en lenguaje natural. `--project` solo acepta proyectos existentes. El **BibTeX lo genera el código**, nunca el LLM.
- **Duplicados:** hash del PDF → DOI normalizado → título difuso.
- **Sin depender de ningún gestor bibliográfico:** una biblioteca existente se trae con un `.bib` (conservando citekeys) y sus PDFs en `inbox/`.
- **Licencia AGPL-3.0-or-later**, la que exige PyMuPDF, el extractor de PDF.

## Cambios en v0.2 (tus 17 comentarios)

| # | Comentario | Cambio en el plan | Dónde |
|---|---|---|---|
| 1 | Ingerir por DOI o desde `inbox/` | `sb ingest` acepta nada (todo `inbox/`), DOIs, una lista de DOIs o rutas a PDFs | §5.1 |
| 2 | Nada corriendo todo el tiempo | Principio nuevo; `sb chat`, `sb ask`; la ingesta procesa sin agente | §2, §5.3, §6.2 |
| 3 | iMac, MacBook Pro M5 64 GB, Mac mini | Tabla de máquinas y perfiles por máquina | §1.2, §3.5 |
| 4 | Sin instalaciones globales | Todo con `uv`; alias en vez de `uv tool install`; lista corta de excepciones de sistema | §2, §8.2 |
| 5 | Código instalable desde otro repo | Sí: dos repos; el de datos depende del de código vía git | §3 |
| 6 | Dejar Zotero, disco al 88% | Importación única que mueve PDFs y conserva citekeys; política de espacio en disco | §5.7, §10 |
| 7, 15 | Acceso institucional; pedir VPN si falla | Descarga institucional con detección de red UNAM y mensaje de VPN | §5.2 |
| 8 | Solo CLI | Interfaz gráfica fuera de alcance | §1.3 |
| 9 | `inbox/` y `pdfs/` en git, vacías | `.gitkeep` + reglas de `.gitignore` | §3.4 |
| 10 | Región, país, ciudad; experimental/numérico/ambos | Bloque `classification` en cada artículo, con vocabulario configurable y filtros | §4.2, §5.3 |
| 11, 13, 14 | Cómo se agrega un proyecto; lenguaje natural; tipos de proyecto | Flujo completo de proyectos, skill `sb-proyectos`, `kind` opcional con vocabulario en `config.toml` | §5.5 |
| 12 | ¿Qué es `sb`? | Explicación | §6.1 |
| 16 | ¿Qué va en `config.local.toml`? | Desaparece: perfiles por máquina en el repo privado + `.env` solo para secretos | §3.5 |
| 17 | `uv run sb --help` | Sí; ayuda por comando | §6.1 |

## Cambios en v0.3 (segunda ronda)

| # | Comentario | Cambio en el plan | Dónde |
|---|---|---|---|
| 1 | Sin `ingest.sh` | Eliminado: `uv run sb ingest` ya lo hace | §5.1 |
| 2 | Crear los dos repos; compartir el código | Creados `second-brain` (código) y `biblioteca` (datos), ambos privados en GitHub; el código no contiene nada personal ni de la UNAM | §3.1 |
| 3 | Claude en el iMac | Decidido: `backend = "claude"` en el perfil del iMac | §3.5 |
| 4 | `biblioteca` | Decidido (D10) | §3.1 |
| 5 | Región = estado, provincia, país, lo que haya | Campos `country`, `region`, `locality`, todos opcionales | §4.2 |
| 6 | Borrar los PDFs tras extraer | Política por defecto; se borran solo cuando texto y figuras están verificados | §5.1, §10 |
| 7 | ¿Interpretar figuras? | Sí: descripción de cada figura con un modelo con visión, al ingerir | §5.9 |
| 8 | OpenVPN con IP de la UNAM | Detección por IP (rangos verificados en LACNIC) | §5.2 |
| 9 | Prescindir de Zotero | Migración con números reales de tu biblioteca | §5.7 |

## Cambios en v0.4 (tercera ronda)

| Comentario | Cambio en el plan | Dónde |
|---|---|---|
| No quedar ligado a Zotero | Se elimina `sb import zotero`; en su lugar, `sb import bib` (cualquier `.bib`) + PDFs en `inbox/` | §5.7 |
| Mac mini: Intel, 48 GB, con Claude | Perfil igual al del iMac: procesa y consulta con Claude | §1.2 |
| Licencia MIT | Licencia MIT; PyMuPDF (AGPL) se sustituye por extractores permisivos; la CI vigila las licencias | §1.2, §8.1 |
| PDFs ingeridos a un directorio, locales, sin respaldo | Se mueven a `pdfs/` y se conservan; ya no se borran | §5.1, §10 |

## Cambios en v0.5

| Comentario | Cambio en el plan | Dónde |
|---|---|---|
| Volver a PyMuPDF y cambiar la licencia | Extractor `pymupdf4llm`; licencia AGPL-3.0-or-later en lugar de MIT | §1.2, §8.1 |

## Índice

1. Objetivo y requisitos
2. Principios de diseño
3. Arquitectura: dos repositorios
4. Modelo de datos
5. Flujos de trabajo
6. Interfaz: CLI y agentes
7. Búsqueda e índice
8. Stack tecnológico y dependencias
9. Hoja de ruta por fases
10. Logística que conviene no olvidar
11. Documentación del proyecto
12. Calidad: pruebas, CI y evaluaciones
13. Riesgos y mitigaciones
14. Respuestas rápidas
15. Decisiones abiertas
16. Bitácora de decisiones

---

## 1. Objetivo y requisitos

### 1.1 Requisitos

| ID | Requisito | Dónde se resuelve |
|---|---|---|
| R1 | Ingerir todos los PDFs que estén en `inbox/` | §5.1 |
| R2 | Ingerir a partir de uno o varios DOIs, descargando el PDF | §5.1, §5.2 |
| R3 | Registrar el DOI y los metadatos | §5.1 |
| R4 | Mover el PDF a una carpeta solo local | §3.4, §5.1 |
| R5 | Detectar artículos repetidos | §5.4 |
| R6 | Procesar cada artículo con un LLM: resumen y clasificación | §5.3 |
| R7 | Clasificar: experimental / numérico / ambos; país, región, ciudad | §4.2 |
| R8 | "¿Qué artículo habla de X?" → artículo + resumen | §5.6 |
| R9 | Preguntar detalles y que se responda solo con el contenido del artículo | §5.6, §6.4 |
| R10 | Crear proyectos y asignar artículos, también en lenguaje natural | §5.5 |
| R11 | Obtener el BibTeX de los artículos de un proyecto | §5.5 |
| R12 | Sincronizar con GitHub sin archivos de más de 100 MB | §3.4 |
| R13 | Recuperar PDFs a partir del DOI (pidiendo el VPN si hace falta) | §5.2 |
| R14 | Nada corriendo en segundo plano; todo bajo demanda | §2, §6.2 |
| R15 | Funcionar en varias Macs, cada una con su configuración | §1.2, §3.5 |
| R16 | Sin instalaciones globales cuando exista alternativa con `uv` | §8.2 |
| R17 | Traer una biblioteca existente sin depender de Zotero ni de otro gestor | §5.7 |
| R18 | Interpretar las figuras de los artículos | §5.9 |
| R19 | Guardar los PDFs ingeridos en una carpeta local, fuera de git | §5.1 |

### 1.2 Restricciones y contexto

- **GitHub:** bloquea archivos > 100 MiB (advierte desde 50 MiB) y recomienda repositorios de menos de 1 GB.
- **Derechos de autor:** el texto completo y los PDFs no se publican → repo de datos **privado**; PDFs nunca en git.
- **Acceso institucional:** acceso a casi cualquier artículo desde la red de la UNAM o con su OpenVPN, que te da una IP de la UNAM (`132.247.0.0/16` y `132.248.0.0/16`, verificados en LACNIC).
- **Disco:** el iMac tiene 1.3 TB libres (30% usado); guardar los PDFs en local no es problema.
- **Máquinas** (cada una decide qué usar en su perfil, §3.5):

| Máquina | Hardware | LLM local con Ollama | Uso sugerido (lo decides tú en el perfil) |
|---|---|---|---|
| iMac (actual) | Intel i5-8500, solo CPU, 48 GB, macOS 12.7.4 | Lento: sirve para respuestas cortas con modelos MoE de pocos parámetros activos | **Decidido:** procesar con Claude; consultas con Claude o `sb ask` local |
| MacBook Pro M5 | Apple Silicon (GPU Metal), 64 GB | Cómodo con modelos de ~20–35B; procesar prompts largos es viable | Procesar y consultar en local, sin internet |
| Mac mini | Intel, solo CPU, 48 GB | Igual que el iMac | **Decidido:** procesar y consultar con Claude |

- **Consecuencias para el diseño:**
  - El **extractor de PDF debe ser el mismo en todas las máquinas**, porque el texto completo se versiona: si cada Mac extrajera distinto, habría diffs falsos. Versión fijada en `uv.lock`.
  - **Extractor:** `pymupdf4llm` (PyMuPDF), que funciona en Intel y Apple Silicon y da buen Markdown (encabezados, columnas, tablas, OCR con Tesseract). Es AGPL-3.0, y por eso el código también lo es (§8.1). docling y marker requieren PyTorch, que ya no publica binarios para Mac Intel con Python 3.13.
  - LM Studio y MLX solo funcionan en Apple Silicon → Ollama es el denominador común.
  - Tesseract (OCR) ya está instalado en el iMac; en las otras Macs, `brew install tesseract` (§8.2).
- **Entorno:** Python 3.13 gestionado con `uv`.

### 1.3 Fuera de alcance (por ahora)

- Interfaz gráfica: solo CLI y agentes (Claude Code, OpenCode).
- Servicios en segundo plano (vigilar `inbox/`, servidores permanentes).
- Uso multiusuario.
- Descarga masiva o sistemática desde editoriales (§10).
- Formatos distintos de PDF (EPUB, DOCX, HTML).
- Ecuaciones como LaTeX exacto: el extractor las conserva como texto aproximado.

### 1.4 Experiencia objetivo

```text
# Ingesta: no hace falta abrir ningún agente
$ cp ~/Downloads/*.pdf inbox/
$ uv run sb ingest
  ✓ 4 ingeridos y procesados · 1 duplicado (garcia2021thermal ya existía) · 1 por revisar (DOI dudoso)

$ uv run sb ingest 10.1016/j.enbuild.2021.110987 10.1016/j.solener.2020.01.001
  ✓ lopez2019ventilation: PDF de acceso abierto (Unpaywall)
  ✗ perez2020cooling: la editorial pidió autenticación.
    No estás en la red UNAM. Activa el VPN y presiona Enter para reintentar ([s] lo deja pendiente):

# Consulta: abre el agente ya configurado
$ uv run sb chat                      # Claude Code; o: uv run sb chat opencode
> ¿qué artículos numéricos tengo sobre ventilación nocturna en México?
  1. lopez2019ventilation (2019) · numérico · Hermosillo, Sonora, MX — En una frase: …
> ¿qué tasa de ventilación usaron?
  … [lopez2019ventilation, p. 5]. El artículo no reporta la tasa para el caso B.
> crea un proyecto para mi tesis doctoral y agrega estos dos
  Propongo: tesis-doctoral · tipo tesis · "Confort térmico en vivienda social". ¿Lo creo?
> sí, y dame el bib
  $ uv run sb bib --project tesis-doctoral -o ~/tesis/refs.bib   → 2 entradas

# Pregunta suelta, sin abrir chat
$ uv run sb ask "¿qué artículos experimentales hay sobre techos verdes en clima cálido?"
```

---

## 2. Principios de diseño

1. **Texto plano como fuente de verdad.** Todo lo importante vive en Markdown/YAML legible y versionado. Cualquier base de datos (SQLite, embeddings) es *derivada*: desechable y reconstruible con un comando.
2. **Bajo demanda.** Nada corre en segundo plano. Cada comando hace su trabajo y termina. El servidor MCP lo arranca el agente al abrir la sesión y muere con ella. Lo único que debe estar abierto para usar un modelo local es Ollama, y `sb` avisa si no lo está.
3. **Sin instalaciones globales.** Todo lo que es Python se instala con `uv` dentro del proyecto y se ejecuta con `uv run`. Solo las herramientas de sistema que no son de Python quedan fuera (§8.2).
4. **Determinista donde se puede, LLM donde hace falta juicio.** Extraer texto, encontrar el DOI, descargar, deduplicar, mover archivos y generar BibTeX es trabajo del código. Resumir, clasificar, responder y sugerir proyectos es trabajo del LLM. El LLM **nunca** genera BibTeX ni metadatos bibliográficos de memoria.
5. **Código y datos separados**, en dos repositorios (§3). El código no asume dónde está la biblioteca. Los datos fijan qué versión del código usan.
6. **Un archivo por artículo** (por tipo de contenido) → diffs pequeños y casi ningún conflicto entre máquinas.
7. **Identificadores estables.** El *citekey* se asigna una vez y nunca cambia (tus `.tex` dependen de él). El DOI normalizado es la llave de deduplicación.
8. **Todo lo que genera un LLM registra su procedencia** (modelo, versión del prompt, máquina, fecha, hash del texto fuente) para regenerarlo selectivamente.
9. **Agnóstico del agente.** Un núcleo en Python con dos fachadas: CLI (`sb`) y servidor MCP. Reglas y flujos en `AGENTS.md` y en *skills* que leen Claude Code y OpenCode.
10. **Respuestas fundamentadas.** Toda afirmación sobre un artículo se cita como `[citekey, p. N]`. Si algo no está en el texto, se dice explícitamente.
11. **Nunca perder un PDF.** Mover es copiar → verificar hash → borrar el original de `inbox/`. Todas las operaciones son idempotentes y atómicas.
12. **El código es compartible.** Nada personal ni específico de una institución en el código: correo, rangos de IP, mensaje de VPN y vocabularios viven en la configuración de cada biblioteca. Licencia AGPL-3.0-or-later.

---

## 3. Arquitectura: dos repositorios

### 3.1 Por qué dos repos y cómo se conectan

`uv` puede instalar un paquete directamente desde un repositorio de GitHub y fijar el commit exacto en `uv.lock`. Por eso:

| Repo | Contenido | Visibilidad |
|---|---|---|
| `second-brain` → [AltamarMx/second-brain](https://github.com/AltamarMx/second-brain), local en `~/second-brain` | Código: paquete `second_brain`, pruebas, documentación técnica, plantillas de skills y de `AGENTS.md` | Licencia AGPL-3.0-or-later. **Público** desde el 2026-10-04 |
| `biblioteca` → [AltamarMx/biblioteca](https://github.com/AltamarMx/biblioteca), local en `~/biblioteca` | Datos: `library/`, `inbox/`, `pdfs/`, configuración, perfiles de máquina, skills y `AGENTS.md` generados | **Privado siempre** |

El `pyproject.toml` del repo de datos solo declara la dependencia:

```bash
# una sola vez, dentro de ~/biblioteca
uv add "second-brain @ git+https://github.com/AltamarMx/second-brain"
```

- **Usar:** dentro de `~/biblioteca`, `uv run sb …` ejecuta la versión fijada en su `uv.lock`. Todas tus máquinas usan exactamente la misma versión.
- **Actualizar el código en la biblioteca:** `uv lock --upgrade-package second-brain && uv sync`, y luego commit del `uv.lock`. El resto de las máquinas lo reciben con `sb sync`.
- **Desarrollar:** desde el repo de código, `uv run sb --home ~/biblioteca …` prueba el código en desarrollo sobre tus datos reales sin tocar el `uv.lock` de la biblioteca.
- **Acceso:** al ser privado, uv usa tus credenciales de git (las mismas de `git push`) para descargarlo.
- **Otras personas:** clonan o instalan `second-brain`, ejecutan `uv run sb init ~/su-biblioteca` y obtienen su propia biblioteca vacía con su configuración (institución, rangos de IP, correo). Nunca ven tus datos.
- **Compatibilidad:** los datos llevan `schema_version`. Si la biblioteca es más nueva que el código instalado, `sb` se niega a escribir y te dice cómo actualizar (§4.6).

### 3.2 Vista de componentes

```text
   Claude Code  (CLAUDE.md → @AGENTS.md)      OpenCode + Ollama  (AGENTS.md)
        │        (ambos se abren con `uv run sb chat`)      │
        └────────────────┐  skills compartidas  ┌───┘
                         ▼  (.claude/skills/)   ▼
              ┌─────────────────────────────────────────┐
              │   CLI `sb …`          servidor MCP      │  ← fachadas delgadas
              ├─────────────────────────────────────────┤
              │   núcleo Python `second_brain`          │
              │   ingest · fetch · metadata · dedupe ·  │
              │   process (resumen, clasificación,      │
              │   figuras) ·                            │
              │   library · projects · bibtex · import ·│
              │   index · backends (claude/ollama/api)  │
              └─────┬──────────────┬──────────────┬─────┘
                    ▼              ▼              ▼
               library/       pdfs/, inbox/    .cache/
               git: MD+YAML   solo local       índice SQLite (derivado)

   Servicios externos: Crossref · Unpaywall · arXiv · sitios de editoriales (con VPN UNAM)
                       Ollama local · Claude Code (claude -p) · API de Anthropic (opcional)
```

### 3.3 Estructura de directorios

**Repo de código (`second-brain`)**

```text
second-brain/
├── README.md                  # Para desarrollar: instalar, probar, publicar una versión
├── PLAN.md  CHANGELOG.md
├── pyproject.toml  uv.lock    # Paquete + entry points `sb` y `sb-mcp`
├── .pre-commit-config.yaml    # se ejecuta con `uv run pre-commit` (dependencia de desarrollo)
├── .github/workflows/ci.yml   # ruff + pytest
├── src/second_brain/
│   ├── cli.py                 # Comandos `sb` (Typer)
│   ├── mcp_server.py          # Herramientas MCP (mismo núcleo)
│   ├── config.py  machines.py # config.toml + perfil de máquina + .env
│   ├── models.py              # Esquemas pydantic: Paper, Project, FullText, Classification
│   ├── library.py             # ÚNICA capa que lee/escribe library/
│   ├── ingest/                # pipeline, extract, doi, metadata, dedupe
│   ├── fetch/                 # openaccess (Unpaywall/arXiv), publisher, network (¿red UNAM?)
│   ├── process.py             # resumen + clasificación de un artículo
│   ├── figures.py             # localizar figuras, renderizarlas y describirlas
│   ├── backends/              # claude_cli, ollama, anthropic (misma interfaz; texto e imagen)
│   ├── citekey.py  projects.py  bibtex.py  import_bib.py
│   ├── index/                 # SQLite FTS5 (+ sqlite-vec)
│   ├── prompts/               # process.v1.md, answer.v1.md (versionados)
│   └── templates/             # esqueleto del repo de datos: AGENTS.md, skills, README, .gitignore
├── tests/                     # pytest, PDFs sintéticos, respuestas HTTP grabadas
└── docs/                      # uso, arquitectura, formato-datos, desarrollo, decisiones/
```

`main.py` desaparece en la fase 0 (lo sustituye `src/second_brain/cli.py`).

**Repo de datos (`biblioteca`)**, creado por `sb init ~/biblioteca`:

```text
biblioteca/
├── README.md                  # Uso diario (generado)
├── AGENTS.md  CLAUDE.md       # Reglas para agentes (bloque generado por `sb agents sync`)
├── pyproject.toml  uv.lock    # Solo la dependencia second-brain (versión fijada)
├── config.toml                # Preferencias compartidas y vocabularios
├── machines/                  # Un perfil por computadora (en git)
│   ├── imac-ier.toml
│   ├── mbp-m5.toml
│   └── macmini.toml
├── .env.example               # Plantilla de secretos (.env queda fuera de git)
├── .mcp.json  opencode.json   # Servidor MCP para Claude Code y OpenCode
├── .claude/
│   ├── settings.json          # Permisos de Claude Code
│   └── skills/                # sb-ingerir, sb-consultar, sb-proyectos, sb-bibtex
│
├── library/                   # ══ DATOS (en git) ══
│   ├── papers/{citekey}.md    # Metadatos + clasificación (YAML) + resumen
│   ├── fulltext/{citekey}.md  # Texto completo con marcas de página
│   ├── figures/{citekey}.md   # Descripción de cada figura (generada, con procedencia)
│   ├── notes/{citekey}.md     # Tus notas (el programa nunca las toca)
│   └── projects/{slug}.md     # Descripción de cada proyecto
│
├── inbox/.gitkeep             # ══ LOCAL ══ la carpeta existe en git; su contenido no
├── pdfs/.gitkeep              # ══ LOCAL ══ PDFs ya ingeridos ({citekey}.pdf), solo en esta máquina, sin respaldo
└── .cache/                    # ══ DERIVADO ══ index.sqlite, caché HTTP, lock
```

**¿Por qué carpetas por tipo (`papers/`, `fulltext/`, `notes/`)?** Las rutas son predecibles para los agentes (`grep` en `fulltext/` busca solo en textos completos), cada nombre de archivo es único y tus notas quedan aisladas de lo que el programa regenera.

### 3.4 Qué va a git y qué no (repo de datos)

`.gitignore`:

```gitignore
# --- Local: las carpetas existen en git (.gitkeep), su contenido no ---
inbox/*
!inbox/.gitkeep
pdfs/*
!pdfs/.gitkeep
# --- Derivados (se reconstruyen) ---
.cache/
logs/
.venv/
# --- Secretos ---
.env
```

Las subcarpetas `inbox/_errores/` e `inbox/_duplicados/` quedan cubiertas por `inbox/*`. `sb init` crea los `.gitkeep`, y `sb check` falla si algún PDF llegara a entrar al índice de git.

`.gitattributes`:

```gitattributes
* text=auto eol=lf
# GitHub colapsa los diffs del texto completo
library/fulltext/** linguist-generated=true
```

**Tamaño estimado:** ~80–150 KB de Markdown por artículo. 1000 artículos ≈ 100–150 MB en disco y ~30–50 MB dentro de `.git` (git comprime cada objeto). Ningún archivo se acerca a 100 MB.

**¿Comprimir el texto? No.** Git ya comprime (zlib + deltas). Un `.md.gz` casi no ahorra espacio y rompe diffs, `grep` y la lectura por los agentes. Si `library/` pasara de ~1 GB, la salida sería mover `fulltext/` a otro repositorio. Como guardia, `sb check` falla si algún archivo versionado pasa de 10 MB.

### 3.5 Configuración: compartida, por máquina y secretos

Respuesta al comentario 16: **`config.local.toml` desaparece**. Lo que antes iba ahí no es secreto, así que va al repo privado como **perfil de máquina**. Solo las llaves de API quedan fuera de git.

| Archivo | ¿En git? | Contenido |
|---|---|---|
| `config.toml` | Sí | Preferencias de la biblioteca: idioma de resúmenes, formato de citekey, vocabularios, figuras, acceso institucional, correo para Crossref/Unpaywall |
| `machines/{nombre}.toml` | Sí | Lo que depende de cada computadora: modelos, backend de procesamiento, agente por defecto, rutas (PDFs, `.bib` de cada proyecto) |
| `.env` | **No** | Secretos: `ANTHROPIC_API_KEY`, `OPENALEX_API_KEY`, etc. Todos opcionales |

**¿Por qué los secretos no van al repo aunque sea privado?** Porque un repo privado puede compartirse, clonarse en otra máquina o hacerse público por error, y una llave en el historial de git es casi imposible de borrar. GitHub, además, bloquea pushes que contienen llaves.

```toml
# config.toml: compartido
[user]
email = "tu-correo@ier.unam.mx"         # "polite pool" de Crossref; lo exige Unpaywall

[library]
summary_language = "es"
process_prompt = "process.v1"
citekey_format = "{auth}{year}{word}"

[vocab]
study_type = ["experimental", "numerico", "ambos", "teorico", "revision", "otro"]
project_kind = ["tesis", "articulo", "proyecto", "curso", "otro"]

[figures]
describe = true                         # §5.9

[access]                                # acceso institucional (§5.2)
institution = "UNAM"
ip_ranges = ["132.247.0.0/16", "132.248.0.0/16"]   # verificados en LACNIC (2026-10-04)
vpn_hint = "Activa el OpenVPN de la UNAM"
max_downloads_per_run = 30
seconds_between_downloads = 10

[checks]
max_file_mb = 10
```

```toml
# machines/imac-ier.toml: perfil del iMac
[process]                               # resumen, clasificación y figuras al ingerir
backend = "claude"                      # claude | ollama | anthropic | none  (iMac: decidido)

[llm]                                   # consultas: sb ask y sb chat opencode
provider = "ollama"
model = "NOMBRE-DEL-MODELO"
num_ctx = 32768

[chat]
agent = "claude"                        # agente que abre `sb chat` sin argumentos

[embeddings]
model = "NOMBRE-DEL-MODELO-DE-EMBEDDINGS"

[bib_outputs]                           # dónde escribe `sb bib sync` en esta máquina
tesis-doctoral = "~/Documents/tesis/refs.bib"
```

- **¿Cómo sabe `sb` en qué máquina está?** Por la variable `SB_MACHINE` o, si no está definida, por el nombre de la computadora (`scutil --get LocalHostName`), convertido a minúsculas. `sb machine init` crea el perfil de la máquina actual a partir de una plantilla y `sb doctor` muestra cuál está activo.
- **Ubicación de la biblioteca:** opción `--home` → variable `SB_HOME` → búsqueda de `config.toml` hacia arriba desde la carpeta actual.

---

## 4. Modelo de datos

La especificación formal vivirá en `docs/formato-datos.md`: es el **contrato** entre código y datos. Fechas en ISO 8601, texto en UTF-8 (NFC) y serialización determinista (orden fijo de campos) para que los diffs sean mínimos.

### 4.1 Artículo: `library/papers/{citekey}.md`

```markdown
---
schema_version: 1
citekey: garcia2021thermal
type: article-journal              # tipo CSL: article-journal, paper-conference, chapter, book, thesis, report…
doi: 10.5555/ejemplo.2021.0001
ids: {arxiv: null, isbn: null, openalex: null}
title: "Thermal performance of earth-sheltered dwellings in hot climates"
authors:
  - {family: García, given: Ana, orcid: null}
  - {family: Smith, given: John, orcid: null}
year: 2021
container_title: Energy and Buildings
volume: "240"
issue: null
pages: "110987"
publisher: Elsevier
language: en
license: null                      # p. ej. CC-BY, si Crossref lo reporta
abstract: |
  …
keywords: [thermal mass, passive cooling]
tags: []                           # tus etiquetas libres
classification:                    # §4.2
  study_type: ambos
  locations:
    - {country: MX, region: Sonora, locality: Hermosillo, page: 3}
  reviewed: false                  # true cuando la confirmas o corriges
projects:                          # un artículo puede estar en varios proyectos
  tesis-doctoral:
    added: 2026-10-04
    note: "Cap. 2: datos para validar el modelo"
pdf:                               # null si aún no hay PDF; el archivo está en pdfs/{citekey}.pdf
  sha256: 9f2c…                    # sirve para detectar duplicados y re-vincular
  pages: 14
  size_bytes: 2345678
  source: institutional            # inbox | openaccess | institutional
  original_filename: "Garcia_2021.pdf"
figures: 6                         # figuras descritas en library/figures/
status: processed                  # awaiting_pdf, needs_review, needs_processing, processed
flags: []                          # doi_uncertain, metadata_mismatch, ocr, possible_duplicate, pdf_version_mismatch, retracted
added: 2026-10-04
provenance:
  metadata_source: crossref
  extractor: "pymupdf4llm X.Y.Z"
  fulltext_sha256: 4b1d…
  process: {backend: claude, model: claude-opus-5-5, prompt: process.v1, machine: imac-ier, date: 2026-10-04, sha256: 77aa…}
  figures: {backend: claude, model: claude-opus-5-5, prompt: figures.v1, date: 2026-10-04}
---

## En una frase
…

## Problema y objetivo
…

## Datos y métodos
…

## Resultados principales
- … (p. 7)

## Conclusiones
…

## Limitaciones (según los autores)
…
```

### 4.2 Clasificación (comentario 10)

| Campo | Valores | Notas |
|---|---|---|
| `study_type` | `experimental`, `numerico`, `ambos`, `teorico`, `revision`, `otro` | El vocabulario vive en `config.toml` (`[vocab]`): puedes añadir valores sin tocar el código, y `sb check` valida contra él |
| `locations[]` | Lista de `{country, region, locality, page}` | Un artículo puede estudiar varios sitios; lista vacía si no aplica (p. ej., un estudio teórico) |
| `country` | Código ISO 3166-1 alfa-2 (`MX`, `ES`, `US`) | Código para filtrar sin ambigüedad; el nombre se muestra al imprimir |
| `region` | Estado, provincia o departamento (`Sonora`) | — |
| `locality` | Ciudad, municipio o sitio (`Hermosillo`, `Ciudad Universitaria`) | — |

Se llena **lo que el artículo diga**, a cualquier nivel: si solo menciona el país, `region` y `locality` quedan vacíos; si dice "norte de México", eso va en `region` tal cual.
| `page` | Página donde se menciona el sitio | Para verificar de dónde salió |

- Los llena el LLM **al procesar** el artículo (§5.3), en la misma pasada que el resumen, y quedan con `reviewed: false` hasta que los confirmes.
- Se corrigen con `sb meta KEY --set study_type=numerico` o pidiéndoselo al agente.
- Se filtran en la búsqueda: `sb search "ventilación" --study numerico --country MX` o `sb list --locality Hermosillo`.
- **Sugerencia:** si después quieres más ejes (zona climática Köppen, tipo de edificación, escala), se añaden como nuevos campos de clasificación en `config.toml` y `sb process --reclassify` los llena en los artículos existentes.

### 4.3 Texto completo: `library/fulltext/{citekey}.md`

```markdown
---
citekey: garcia2021thermal
source_pdf_sha256: 9f2c…
extractor: "pymupdf4llm X.Y.Z"
extracted: 2026-10-04
pages: 14
ocr: false
---
<!-- page 1 -->
# Thermal performance of earth-sheltered dwellings in hot climates
…
<!-- page 2 -->
## 2. Methods
…
```

Las marcas `<!-- page N -->` no se ven al renderizar, pero permiten citar páginas y recuperar fragmentos por página. No se guardan imágenes.

### 4.4 Proyecto: `library/projects/{slug}.md`

```markdown
---
schema_version: 1
slug: tesis-doctoral
name: "Tesis doctoral: confort térmico en vivienda de interés social"
kind: tesis               # opcional; valores en config.toml → [vocab].project_kind
status: active            # active, paused, archived
created: 2026-10-04
---
Descripción breve: objetivo, preguntas de investigación, palabras clave.
El LLM usa este texto para sugerir a qué proyectos pertenece cada artículo nuevo.
```

- La membresía vive en cada artículo (`projects:`), no en el proyecto: añadir un artículo modifica un solo archivo pequeño y no hay listas gigantes que choquen en los merges.
- La ruta del `.bib` de cada proyecto depende de la máquina → va en el perfil de máquina (`[bib_outputs]`).

### 4.5 Citekeys

- Formato `{apellido}{año}{primera palabra significativa del título}`, en minúsculas ASCII: `garcia2021thermal`. Se omiten artículos y preposiciones (the, a, on, of, el, la, de…).
- Transliteración: `Pérez` → `perez`, `Müller` → `muller`; partículas juntas (`van der Berg` → `vanderberg`).
- Colisión → sufijo: `garcia2021thermal-b`, `-c`…
- **Inmutable** una vez asignado, aunque se corrijan los metadatos.
- **Los artículos importados de un `.bib` conservan su citekey**, para que tus `.tex` existentes sigan compilando (§5.7). Si chocara con uno existente, se avisa y no se importa esa entrada.

### 4.6 Versionado del esquema

- Cada archivo lleva `schema_version`. Un cambio de formato implica `sb migrate` (idempotente y con prueba), una entrada en `CHANGELOG.md` y la actualización de `docs/formato-datos.md`.
- `sb check` valida todo `library/` contra los modelos pydantic y los vocabularios de `config.toml`.
- Si los datos tienen una `schema_version` mayor que la que entiende el código instalado, `sb` se niega a escribir y sugiere `git pull && uv sync`.

---

## 5. Flujos de trabajo

### 5.1 Ingesta: `uv run sb ingest`

No requiere abrir Claude ni OpenCode. Una sola orden con varias entradas:

```bash
uv run sb ingest                         # todos los PDFs de inbox/
uv run sb ingest 10.1016/j.enbuild.2021.110987 10.1016/j.solener.2020.01.001
uv run sb ingest --dois lista.txt        # un DOI por línea
uv run sb ingest ~/Downloads/articulo.pdf
uv run sb ingest --retry                 # reintenta los que quedaron esperando PDF
```

**Desde un DOI:**

1. Normalizar el DOI y comprobar si ya existe (§5.4). Si existe pero sin PDF, solo intenta conseguir el PDF.
2. Metadatos de Crossref (respaldo: DataCite).
3. Conseguir el PDF (§5.2): acceso abierto → acceso institucional → si falla, pedir el VPN o dejarlo en `awaiting_pdf`.
4. Continuar como un PDF, con el DOI ya conocido.

**Desde un PDF** (en `inbox/` o una ruta):

1. **Hash** SHA-256 → ¿duplicado exacto?
2. **Candidatos de DOI**: metadatos del PDF, regex recomendada por Crossref (`10.\d{4,9}/[-._;()/:A-Z0-9]+`, sin distinguir mayúsculas, limpiando la puntuación final) e ID de arXiv.
3. **¿DOI ya registrado?** → duplicado por DOI (§5.4). Si el registro estaba en `awaiting_pdf`, se le adjunta este PDF.
4. **Metadatos** de Crossref y **validación**: el título de Crossref debe aparecer (coincidencia difusa) en la página 1. Si no → `needs_review` (probablemente se capturó el DOI de una referencia citada).
5. **Sin DOI**: búsqueda por título en Crossref → candidato → `needs_review`.
6. **Duplicado difuso** (título + año + primer autor) → flag `possible_duplicate`.
7. **Citekey** (inmutable).
8. **Texto completo** → `library/fulltext/{key}.md` con marcas de página (OCR si no hay capa de texto).
9. **Registro** → `library/papers/{key}.md` con `status: needs_processing`.
10. **Figuras** (§5.9): se localizan, se renderizan y se describen con el backend del perfil.
11. **Procesar** (resumen + clasificación, §5.3), salvo `--no-process` o `backend = "none"`.
12. **Mover el PDF** → `pdfs/{key}.pdf` (copiar → verificar hash → borrar de `inbox/`). Queda solo en esta máquina, fuera de git y sin respaldo.
13. **Proyecto** (`--project slug`, debe existir; §5.5) y **actualización incremental del índice**.
14. **Reporte**: ingeridos · duplicados · por revisar · esperando PDF · errores (`--json` para agentes).

Detalles:

- **Normalización del DOI:** minúsculas, sin prefijos (`https://doi.org/`, `doi:`) y con `%2F` decodificado. Se guarda tal como lo da Crossref y se compara normalizado.
- **Errores:** cada paso es idempotente. Si algo falla, el PDF pasa a `inbox/_errores/` con el motivo en el reporte y al repetir `sb ingest` se continúa donde se quedó.
- **Opciones:** `--dry-run`, `--doi 10.xxx/yyy` (forzar el DOI de un PDF), `--project slug`, `--no-process`, `--limit N` (procesar por partes), `--commit`.
- **Concurrencia:** un *lock* en `.cache/` impide dos ingestas simultáneas.

### 5.2 Descarga de PDFs por DOI (comentarios 7 y 15)

Orden de intentos:

1. **Acceso abierto**, que no requiere VPN: Unpaywall (`best_oa_location.url_for_pdf`) y arXiv.
2. **Acceso institucional:**
   - **Antes de intentar**, `sb` comprueba si tu IP pública está en los rangos de la UNAM (`[access].ip_ranges`); con el OpenVPN activo lo estará. Si no, te avisa: *"No estás en la red UNAM. Activa el OpenVPN de la UNAM y presiona Enter"*. Si no lo activas, el artículo queda en `awaiting_pdf`.
   - Resuelve `https://doi.org/{doi}` hasta la página de la editorial y busca el PDF en la etiqueta `<meta name="citation_pdf_url">`, que usan casi todas las editoriales, o en los enlaces `link` que reporta Crossref.
   - Comprueba que lo descargado **sea realmente un PDF** (empieza con `%PDF`) y que el título coincida. Las editoriales suelen responder con una página HTML de acceso en lugar del PDF.
3. **Si falla:**
   - Respuesta de acceso denegado (401/403, página de login o paywall) → **mensaje de VPN**: *"La editorial pidió autenticación. ¿Está activo el OpenVPN de la UNAM? Actívalo y presiona Enter para reintentar, o [s] para dejarlo pendiente."* Si ya estás en la red UNAM, el mensaje cambia: probablemente la suscripción no cubre esa revista. En modo no interactivo (`--json`, agentes), el estado es `needs_vpn`, y el agente te lo pide con las mismas palabras.
   - Bloqueo anti-robots (algunas editoriales, como ScienceDirect, lo hacen aunque tengas acceso) → `sb pdf open KEY` abre el DOI en tu navegador. Guardas el PDF en `inbox/` y el siguiente `sb ingest` lo asocia solo a su registro (paso 3 de §5.1).
   - Al final de cada ingesta, el reporte recuerda cuántos quedan en `awaiting_pdf` y sugiere `uv run sb ingest --retry` con el VPN activo.
4. **Descartado (2026-10-04):** usar las APIs de minería de texto de Elsevier y Wiley. El usuario prefiere conseguir los PDFs a mano.

Reglas de cortesía, para que una editorial no bloquee a toda la UNAM: una descarga a la vez, una pausa entre descargas (`seconds_between_downloads`) y un máximo por ejecución (`max_downloads_per_run`). Nunca descargas masivas (§10).

`sb pdf status` lista los registros esperando PDF y los que no tienen PDF en esta máquina (p. ej., en una máquina nueva). `sb pdf get KEY` (o `--missing`) los descarga a `pdfs/` con el mismo orden de intentos. `sb pdf open KEY` abre el PDF local, o el DOI en el navegador si no está. Si el PDF recuperado tiene otro hash (preprint, manuscrito aceptado o versión editorial), se conserva y se marca `pdf_version_mismatch`, porque las páginas citadas se refieren al PDF original.

### 5.3 Procesamiento: resumen + clasificación

Cada artículo se procesa **una vez**, en una sola llamada al LLM que devuelve el resumen (plantilla de §4.1) y la clasificación (§4.2). La salida se valida (secciones, vocabulario, código de país) y, si falla, se reintenta una vez.

- **Solo contenido del artículo:** sin crítica externa ni conocimiento general. Entre 250 y 400 palabras, en español, con la página entre paréntesis para cifras y afirmaciones clave.
- **Backends** (cada máquina elige en `[process].backend`):

| Backend | Cómo | Ventajas | Cuidado |
|---|---|---|---|
| `claude` | Claude Code en modo no interactivo (`claude -p`) | Mejor calidad; usa tu suscripción, sin API key | El texto se envía a Anthropic; lotes grandes consumen tu cuota |
| `ollama` | Modelo local del perfil | Privado, sin costo, sin internet | En el iMac (CPU) puede tardar minutos por artículo; en la M5, viable |
| `anthropic` | API de Anthropic (`ANTHROPIC_API_KEY` en `.env`) | Lotes grandes sin supervisión | Tiene costo por uso |
| `none` | No procesa al ingerir | Ingesta rápida | Queda en `needs_processing` hasta que corras `sb process` o se lo pidas al agente |

- **Comandos:** `sb process --pending` (todo lo que falta), `sb process KEY`, `sb process --stale` (regenera lo hecho con un prompt o modelo anterior), `--backend ollama` para forzar uno.
- **Prompts versionados** en `src/second_brain/prompts/process.v1.md`; cambiar el prompt implica una nueva versión.
- Un resumen editado a mano (su hash ya no coincide) no se sobrescribe sin `--force`.
- Documentos largos (tesis, libros) o modelos con poco contexto: se procesa por secciones y luego se sintetiza.

### 5.4 Deduplicación

| Caso | Cómo se detecta | Acción |
|---|---|---|
| Mismo archivo | SHA-256 igual | Si el registro no tiene PDF local, se adjunta; si lo tiene, va a `inbox/_duplicados/` |
| Mismo DOI, otro archivo | DOI normalizado | Igual que arriba; si el hash difiere, `pdf_version_mismatch` |
| DOI que ya está en la biblioteca (ingesta por DOI) | DOI normalizado | Se informa como duplicado y no se descarga nada, salvo que falte el PDF |
| Preprint vs. versión publicada (DOIs distintos) | Título normalizado + año ±1 + primer autor (similitud ≥ 0.93) y relaciones de Crossref (`has-preprint`, `is-preprint-of`) | No se fusiona solo: flag `possible_duplicate` y se te pregunta |
| Sin DOI | Hash + título difuso | Igual que el caso anterior |

Efecto secundario útil: en una máquina nueva, soltar un PDF en `inbox/` lo **re-vincula** automáticamente a su registro existente.

### 5.5 Proyectos y BibTeX (comentarios 11, 13 y 14)

**Qué es un proyecto:** un archivo en `library/projects/{slug}.md` con nombre, tipo opcional y descripción. Los artículos se asignan a él.

**Cómo se crea**, de cualquiera de estas formas:

```bash
uv run sb project create tesis-doctoral \
    --name "Tesis doctoral: confort térmico en vivienda social" \
    --kind tesis --desc "Objetivo…, preguntas…, palabras clave…"
uv run sb project create              # sin argumentos: te pregunta cada dato
```

O en lenguaje natural, dentro de `sb chat`. La skill `sb-proyectos` traduce tu petición a la orden y te la confirma antes de ejecutarla:

```text
> crea un proyecto para mi tesis doctoral sobre confort térmico en vivienda social en Hermosillo
  Propongo:  slug tesis-doctoral · tipo tesis
             nombre "Tesis doctoral: confort térmico en vivienda social"
             descripción "…"
  ¿Lo creo?
> sí
  $ uv run sb project create tesis-doctoral --name "…" --kind tesis --desc "…"
  ✓ Creado. Encontré 6 artículos de tu biblioteca que encajan. ¿Los agrego?
```

**Asignar artículos:**

```bash
uv run sb project add tesis-doctoral garcia2021thermal lopez2019ventilation --note "Cap. 2"
uv run sb ingest --project tesis-doctoral          # todo lo que se ingiera ahora
uv run sb project remove | list | show | archive …
```

o "agrega estos artículos a la tesis" en el chat.

**¿Puedo poner cualquier cosa en `--project`?** No. El proyecto **debe existir**. Así un error de dedo (`tesis_doctoral` contra `tesis-doctoral`) no crea proyectos fantasma. Si no existe, `sb` sugiere el más parecido ("¿quisiste decir tesis-doctoral?") y ofrece crearlo en ese momento. Los slugs solo admiten minúsculas, dígitos y guiones.

**¿Dónde se definen los tipos de proyecto?** En `config.toml`, `[vocab].project_kind` (por defecto: tesis, articulo, proyecto, curso, otro). Es opcional y lo puedes editar. Sirve para filtrar (`sb project list --kind tesis`) y para que el agente entienda el contexto.

**BibTeX:**

- `sb bib --project tesis-doctoral -o refs.bib` · `sb bib --keys k1,k2` · `sb bib --from-tex main.tex` (solo las claves citadas, avisando cuáles faltan) · `sb bib sync` (reescribe los `.bib` de todos los proyectos según `[bib_outputs]` del perfil de la máquina).
- Se genera **desde los registros**, de forma determinista. El LLM nunca escribe entradas.
- Resuelve los problemas típicos: protege mayúsculas (`{CO2}`, `{EnergyPlus}`, `{México}`); convierte el HTML/MathML de Crossref (`<sub>2</sub>`) a LaTeX (`CO$_2$`); escapa `&`, `%`, `_` y acentos; mapea tipos CSL a `@article`, `@inproceedings`, `@incollection`, `@book`, `@phdthesis`, `@techreport`, `@misc`. `--format bibtex` (por defecto) o `--format biblatex`.
- **El agente mantiene el registro:** cuando dices "este artículo me sirve para X", lo añade al proyecto (y propone crearlo si no existe). Al ingerir, sugiere proyectos según sus descripciones.

### 5.6 Consulta y preguntas fundamentadas

**¿Transcribir todo o consultar según se requiera? Las dos cosas.** Se transcribe todo **una vez**, al ingerir. Al preguntar se consulta **solo lo necesario**: primero los resúmenes, luego los fragmentos relevantes y el texto completo de un artículo solo si cabe en el contexto del modelo.

Tres niveles:

1. **"¿Qué artículos hablan de X?"** → `sb search "X" [--study …] [--country …] [--project …] [--year 2015..2024]` devuelve citekey, título, año, clasificación, "En una frase" y los fragmentos que coinciden.
2. **Detalles de un artículo** → `sb passages "pregunta" --paper KEY` o `sb text KEY --pages 4-6`. Con Claude, un artículo corto se puede leer completo. Cita: `[garcia2021thermal, p. 6]`.
3. **Comparar varios artículos** → fragmentos de cada uno → tabla con una cita en cada celda.

Reglas de respuesta (en `AGENTS.md`):

- Responder solo con información leída en la sesión desde `library/`.
- Cada afirmación lleva su cita `[citekey, p. N]`; para datos numéricos, citas textuales breves.
- Si no aparece tras buscar: "El artículo no lo menciona" (diciendo qué se buscó). Nunca se rellena con conocimiento general; si lo pides, va aparte y etiquetado.
- Preguntas en español sobre artículos en inglés: buscar también con los términos en inglés, hasta tener embeddings multilingües (fase 7).

### 5.7 Traer una biblioteca existente (sin depender de ningún gestor)

El código no sabe nada de Zotero ni de ningún otro gestor bibliográfico. Para traer artículos que ya tienes hay dos entradas genéricas:

```bash
uv run sb import bib refs.bib --dry-run          # qué se registraría, duplicados, choques de citekey
uv run sb import bib refs.bib [--project slug]   # un registro por entrada, conservando su citekey
cp carpeta-con-pdfs/*.pdf inbox/ && uv run sb ingest   # cada PDF se asocia a su registro
```

- `sb import bib` lee cualquier `.bib`: de Zotero, Mendeley, JabRef o escrito a mano. Con DOI, los metadatos vienen de Crossref; sin DOI, del `.bib`. **El citekey del `.bib` se conserva**, y los `keywords` pasan a `tags`. Las entradas quedan en `awaiting_pdf` hasta que llegue su PDF.
- Al soltar los PDFs en `inbox/`, la ingesta los asocia a su registro por DOI o, si no tienen, por título (§5.4). Los que no tengan PDF pueden quedarse así (solo metadatos) o descargarse con `sb pdf get --missing`, por partes.
- **Proyectos:** exporta un `.bib` por grupo o colección e impórtalo con `--project`.
- **Tu caso, una sola vez:** desde Zotero, Archivo → Exportar biblioteca → BibTeX (o una colección a la vez), y copia los PDFs de `~/Zotero/storage/*/` a `inbox/`. Como referencia, son 331 elementos, 248 con DOI, 419 PDFs (1.8 GB), 8 colecciones y 20 citekeys. Después puedes desinstalar Zotero: nada en el código depende de él.
- Es un lote grande para la cuota de Claude: conviene ingerir por partes (`uv run sb ingest --limit 50`).

### 5.8 Sincronización y máquina nueva

- `sb sync` = `git pull --rebase` → `uv sync` (si cambió `uv.lock`) → `sb index update` → `sb check` → `git push`.
- **Máquina nueva** (nada global salvo §8.2):
  1. `git clone` del repo `biblioteca` → `uv sync` (instala `second-brain` desde GitHub, versión fijada).
  2. `uv run sb doctor`: comprueba uv, git, Tesseract, Ollama, Claude Code y OpenCode, y te dice qué falta.
  3. `uv run sb machine init`: crea `machines/{nombre}.toml` (modelos, backend, rutas) y `.env` si hace falta.
  4. `uv run sb index rebuild`.
  5. Los PDFs no se sincronizan: cada máquina tiene los suyos. Como el texto y las figuras ya están en git, no hace falta descargarlos todos. Si necesitas ver uno, usa `sb pdf get KEY` (con el OpenVPN).

### 5.9 Figuras (comentario 7)

**Sí se pueden interpretar.** Las figuras se interpretan **al ingerir** y lo que queda es texto, disponible en todas tus máquinas aunque el PDF solo esté en una:

1. **Localizar:** PyMuPDF encuentra los pies de figura ("Fig. 3", "Figure 3") y las imágenes de cada página. Muchas gráficas son vectoriales (no son imágenes incrustadas), así que se renderiza la región de la figura a PNG, o la página completa si no se puede delimitar. Los PNG son temporales (`.cache/`).
2. **Describir:** un modelo con visión recibe la imagen, su pie de figura y el párrafo que la cita, y devuelve:
   - tipo: gráfica de líneas, barras, mapa, esquema, fotografía, diagrama…;
   - variables, ejes y unidades;
   - qué muestra y tendencias principales;
   - valores legibles, marcados como aproximados;
   - relación con el texto.
3. **Guardar** en `library/figures/{key}.md`:

```markdown
---
citekey: lopez2019ventilation
figures:
  - {id: fig3, page: 5, kind: line-chart}
provenance: {backend: claude, model: claude-opus-5-5, prompt: figures.v1, date: 2026-10-04}
---
## Fig. 3 (p. 5)
**Pie:** "Indoor air temperature for cases A and B during July."
**Descripción (generada):** Gráfica de líneas de temperatura interior (°C, eje y, ~24–36)
contra hora del día (eje x). El caso B se mantiene ~2–3 °C por debajo del A entre las
14 y las 18 h (valores leídos de la gráfica, aproximados).
```

4. **Buscar:** las descripciones se indexan como fragmentos con su página, así que "¿en qué figura se ve la temperatura interior?" funciona.

- **Backends:** `claude` (Claude Code lee imágenes; es lo que usará el iMac), `ollama` con un modelo de visión (lento en CPU, viable en la M5) o `anthropic`.
- **Regla de respuesta:** una cifra tomada de una figura se cita como `[citekey, Fig. 3, p. 5]` y se aclara que es una lectura aproximada de la gráfica. Si el texto da la cifra, el texto tiene prioridad.
- **Límites:** los valores leídos de gráficas son aproximados; las figuras muy densas (mapas, mosaicos de fotos) se describen en términos generales; las ecuaciones no se tratan como figuras. Cuesta más cuota: un artículo típico tiene de 5 a 10 figuras, que se envían juntas en una sola llamada.
- **Tablas:** pymupdf4llm las extrae como tablas Markdown en el texto completo. Si una tabla es una imagen, se trata como figura.
- `[figures].describe = false` lo desactiva. `sb figures KEY` vuelve a describir las figuras de un artículo, usando el PDF local (o descargándolo con `sb pdf get` si esta máquina no lo tiene).

---

## 6. Interfaz: CLI y agentes

### 6.1 ¿Qué es `sb`? (comentarios 12 y 17)

`sb` (de *second brain*) es el **nombre del programa de línea de comandos** de este proyecto: la puerta de entrada única al código. No es un servicio ni algo que se instala aparte. Se declara en el `pyproject.toml` del paquete:

```toml
[project.scripts]
sb = "second_brain.cli:app"
sb-mcp = "second_brain.mcp_server:main"
```

Al hacer `uv sync`, uv crea `.venv/bin/sb` dentro del proyecto, y `uv run sb …` lo ejecuta con las dependencias correctas, sin instalar nada global. Tú lo usas directamente para ingerir, crear proyectos o sacar un `.bib`. Los agentes (Claude Code, OpenCode) lo usan como herramienta. El nombre se puede cambiar (D9).

**Ayuda:** sí, `uv run sb --help` lista todos los comandos, y `uv run sb ingest --help` (o cualquier comando) explica sus opciones con ejemplos. `uv run sb` sin argumentos muestra la ayuda general.

**Desde otra carpeta** (p. ej., la de tu `.tex`), sin instalación global, con un alias en `~/.zshrc`:

```bash
alias sb='SB_HOME=~/biblioteca uv run --project ~/biblioteca sb'
# luego, desde ~/tesis:
sb bib --from-tex main.tex -o refs.bib
```

| Comando | Qué hace |
|---|---|
| `sb init RUTA` | Crea el repo de datos (carpetas, `.gitkeep`, config, skills, `AGENTS.md`, hook de git) |
| `sb machine init` / `sb doctor` | Perfil de esta máquina / diagnóstico de dependencias y configuración |
| `sb ingest [PDFs… \| DOIs…] [--dois F] [--retry]` | Ingesta (por defecto, todo `inbox/`) |
| `sb process [KEY \| --pending \| --stale]` | Resumen + clasificación |
| `sb figures KEY` | Volver a describir las figuras de un artículo |
| `sb status` | Pendientes: inbox, por revisar, esperando PDF, sin procesar |
| `sb show KEY` | Metadatos + clasificación + resumen |
| `sb text KEY [--pages A-B] [--section S]` | Texto completo o una parte |
| `sb search "consulta" [filtros]` / `sb list [filtros]` | Búsqueda / listado (filtros: `--project`, `--study`, `--country`, `--region`, `--locality`, `--year`) |
| `sb passages "consulta" [--paper KEY]` | Fragmentos con página y sección |
| `sb meta KEY --refresh` / `--set campo=valor` | Refrescar metadatos desde Crossref o corregirlos |
| `sb project create/add/remove/list/show/archive` | Proyectos |
| `sb bib …` | BibTeX por proyecto, por claves o desde un `.tex` |
| `sb pdf status/get/open` | PDFs: faltantes o esperando descarga, descargar a `pdfs/`, abrir el local o el DOI |
| `sb import bib FILE.bib` | Registrar las entradas de un `.bib` existente, conservando sus citekeys |
| `sb chat [claude \| opencode]` | Abre el agente en la biblioteca, ya configurado |
| `sb ask "pregunta" [--paper KEY]` | Pregunta suelta con el LLM del perfil, sin abrir chat |
| `sb index update/rebuild` | Índice derivado |
| `sb check` | Valida esquema, vocabularios, DOIs únicos, proyectos referenciados, tamaños y que no haya PDFs en git |
| `sb sync` | pull → sync → índice → check → push |
| `sb agents sync` | Actualiza skills y `AGENTS.md` desde las plantillas del paquete |
| `sb migrate` | Migraciones de esquema |
| `sb remove KEY` | Elimina un artículo (git conserva el historial) |

Todos los comandos aceptan `--json` para agentes; la salida por defecto es legible para humanos (`rich`).

### 6.2 Abrir el chat: `sb chat` (comentario 2)

- `uv run sb chat` abre el agente por defecto del perfil (`[chat].agent`).
- `uv run sb chat claude` → ejecuta `claude` en la carpeta de la biblioteca: carga `CLAUDE.md`, las skills y el MCP.
- `uv run sb chat opencode` → comprueba que Ollama esté abierto (si no, te lo dice), y abre OpenCode con el modelo del perfil de esta máquina.
- Al salir del chat no queda nada corriendo: el servidor MCP se cierra con la sesión.
- `uv run sb ask "…"` es la vía más rápida para una pregunta suelta: busca fragmentos, arma un prompt mínimo y responde con citas usando `[llm]` del perfil (Ollama, o `claude -p`).

### 6.3 Servidor MCP (`sb-mcp`)

Expone las mismas funciones del núcleo como herramientas tipadas, que los modelos locales usan mucho mejor que una línea de comandos libre. El agente lo arranca por stdio al abrir la sesión:

- **Lectura:** `search_papers` (con filtros de clasificación), `search_passages`, `get_paper`, `get_fulltext` (paginado), `list_projects`, `get_project`, `export_bibtex`, `library_status`.
- **Escritura:** `ingest`, `process_paper`, `create_project`, `add_to_project`, `remove_from_project`, `set_classification`.

### 6.4 Reglas y flujos para agentes

- `AGENTS.md` es la **fuente única** de reglas. OpenCode la lee directamente; `CLAUDE.md` contiene `@AGENTS.md` más notas propias de Claude Code.
- Las plantillas viven en el paquete (`src/second_brain/templates/`) y `sb agents sync` las copia al repo de datos. Así, al actualizar el código, también se actualizan los flujos. Tus skills propias (sin prefijo `sb-`) no se tocan.
- **Skills** en `.claude/skills/` (las leen Claude Code y OpenCode):
  - `sb-ingerir`: correr `sb ingest --json`; si hay `needs_vpn`, pedirte que actives el VPN y reintentar; resolver contigo los `needs_review`; procesar los pendientes si el backend es `none`; sugerir proyectos.
  - `sb-consultar`: búsqueda (con filtros de clasificación) → resumen → fragmentos → respuesta con citas.
  - `sb-proyectos`: crear, asignar y quitar en lenguaje natural; siempre muestra la orden `sb project …` y pide confirmación antes de crear.
  - `sb-bibtex`: generar o actualizar `.bib` y verificar las claves de un `.tex`.

Contenido mínimo de `AGENTS.md`:

1. Qué es el repositorio y mapa de carpetas.
2. Escribir en `library/` **solo** mediante `sb` (excepto `library/notes/`, cuando lo pidas). Leer, libremente.
3. Nunca generar BibTeX ni metadatos de memoria: siempre `sb bib` / `sb show`.
4. Reglas de respuesta fundamentada (§5.6).
5. Ante un DOI dudoso, un posible duplicado o la creación de un proyecto, preguntar antes.
6. Si una descarga falla por acceso, pedir el OpenVPN de la UNAM (`[access].vpn_hint`); nunca intentar evadir el bloqueo.
7. Las cifras tomadas de descripciones de figuras se citan con figura y página y se presentan como aproximadas.
8. No abrir PDFs si existe el texto completo.
9. Convenciones de commit: `ingest: …`, `project: …`, `process: …`.

### 6.5 Claude Code

- `.claude/settings.json`: permitir `Bash(uv run sb:*)` sin confirmación; denegar la edición directa de `library/papers/` y `library/fulltext/`, lo que obliga a pasar por `sb`.
- Hook `SessionStart` que ejecuta `uv run sb status`: al abrir la sesión, Claude ya sabe si hay PDFs en `inbox/`, artículos por revisar o esperando PDF.
- `.mcp.json`:

```json
{
  "mcpServers": {
    "second-brain": { "command": "uv", "args": ["run", "sb-mcp"] }
  }
}
```

### 6.6 OpenCode + Ollama

`opencode.json` (compartido; el modelo concreto lo pasa `sb chat opencode` desde el perfil de la máquina, con la opción de modelo de OpenCode o un archivo de configuración generado; a verificar en la fase 6):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" }
    }
  },
  "mcp": {
    "second-brain": { "type": "local", "command": ["uv", "run", "sb-mcp"], "enabled": true }
  }
}
```

- **Agente `bibliotecario`** (`.opencode/agents/bibliotecario.md`): sin edición, `bash` en modo `ask`, con las herramientas MCP y un prompt de sistema corto.
- **Contexto:** Ollama usa por defecto 4096 tokens, y OpenCode necesita 16k–32k para que funcionen las llamadas a herramientas. `sb machine init` puede crear una variante del modelo con `num_ctx` ampliado (un `Modelfile` con `PARAMETER num_ctx 32768`), para no depender de variables de entorno al abrir Ollama.
- **Modelos por máquina** (revisar los vigentes al implementar; deben soportar *tool calling*):
  - **iMac (CPU):** MoE con pocos parámetros activos (en su momento, p. ej., Qwen3-30B-A3B o gpt-oss-20b). Unos 5–10 tokens/s y varios minutos para procesar un prompt de 10k tokens: solo fragmentos y respuestas breves.
  - **MacBook Pro M5 (64 GB):** los mismos modelos corren mucho más rápido con la GPU, y caben modelos más grandes. Ahí sí es viable procesar artículos completos en local.
  - **Mac mini (Intel, 48 GB):** igual que el iMac; usa Claude.
- La fase 6 mide tiempos reales en cada máquina y los documenta en `docs/maquinas.md`.

---

## 7. Búsqueda e índice

### 7.1 Índice derivado: `.cache/index.sqlite` (fuera de git)

- `papers`: metadatos y clasificación para filtrar por proyecto, año, tipo de estudio, país, región, ciudad y estado.
- `papers_fts` (FTS5): título, autores, abstract, resumen y palabras clave.
- `chunks` (citekey, página inicial y final, sección, texto) + `chunks_fts` (FTS5). Incluye las descripciones de figuras, marcadas como tales.
- `chunks_vec`: embeddings con `sqlite-vec` (fase 7).
- `meta`: versión del índice y modelo de embeddings.
- Actualización incremental por hash de cada archivo. Si cambia el modelo de embeddings, se reindexa todo.
- Tokenizador FTS5: `porter unicode61 remove_diacritics 2`.

### 7.2 Fragmentación (chunking)

- Por sección y párrafo, de ~300 a 600 palabras con un solapamiento pequeño; cada fragmento conserva su página y su sección.
- Al indexar se antepone contexto ("título | sección").
- La sección de referencias se excluye de los embeddings, pero se conserva en el texto completo.

### 7.3 Estrategia de búsqueda

- **Fase 4, léxica:** BM25 con FTS5 + filtros de clasificación; el agente reformula la consulta.
- **Fase 7, híbrida:** BM25 + embeddings multilingües locales (vía Ollama), fusionados con *Reciprocal Rank Fusion*. Resuelve preguntas en español sobre artículos en inglés. Modelos pequeños: p. ej. `embeddinggemma`, `qwen3-embedding:0.6b` o `bge-m3` (revisar los vigentes).
- **Costo estimado:** 1000 artículos ≈ 40 000 fragmentos → indexado inicial de ~20–60 min en el iMac y mucho menos en la M5, una vez por máquina; después es incremental.

---

## 8. Stack tecnológico y dependencias

### 8.1 Paquetes de Python (todos con `uv`)

| Necesidad | Elección | Alternativas / notas |
|---|---|---|
| Entorno | `uv`, Python 3.13 | `uv.lock` versionado en ambos repos |
| CLI | `typer` + `rich` | `click` |
| Esquemas y validación | `pydantic` v2 | — |
| YAML / frontmatter | `ruamel.yaml` (orden estable) | `python-frontmatter` + PyYAML |
| PDF → Markdown | `pymupdf4llm` (Intel y Apple Silicon, misma salida) | docling/marker requieren PyTorch: no viables en el iMac |
| OCR | Tesseract vía pymupdf4llm | — |
| HTTP | `httpx`, con caché en `.cache/http/` | — |
| HTML de editoriales | `selectolax` o `beautifulsoup4` (leer `citation_pdf_url`) | — |
| Metadatos | Crossref (principal) | DataCite; OpenAlex (opcional) |
| PDF de acceso abierto | Unpaywall, arXiv | OpenAlex, Semantic Scholar |
| Figuras | PyMuPDF (localizar y renderizar) + modelo con visión del backend | — |
| Duplicados difusos | `rapidfuzz` | — |
| Índice | SQLite FTS5 + `sqlite-vec` | LanceDB, Chroma |
| LLM | Cliente `openai` hacia Ollama; `anthropic` opcional; `claude -p` vía subproceso | `litellm` |
| MCP | SDK oficial `mcp` (FastMCP) | — |
| BibTeX | Generador propio + `pylatexenc` | `bibtexparser` v2 para leer `.bib` existentes |
| Calidad | `pytest`, `ruff`, `pre-commit` (como dependencias de desarrollo, con `uv run`) | `mypy` / `pyright` |

**Licencias:** PyMuPDF y pymupdf4llm son AGPL-3.0, así que el código se publica como **AGPL-3.0-or-later**. Para ti no cambia nada. Quien reciba el código puede usarlo y modificarlo libremente, pero si lo redistribuye (o lo ofrece como servicio en red) debe hacerlo con su código fuente y bajo la misma licencia. El resto de las dependencias son permisivas (MIT, BSD, Apache) y compatibles con la AGPL.

### 8.2 Excepciones: herramientas de sistema (comentario 4)

No son de Python y no se pueden instalar con `uv`. `sb doctor` comprueba que estén:

| Herramienta | Para qué | Cómo |
|---|---|---|
| `git`, `uv` | Base | Ya instalados |
| Tesseract | OCR de PDFs escaneados | `brew install tesseract` (ya está en el iMac) |
| Ollama | Modelos locales | App de Ollama |
| Claude Code | Agente y backend `claude` | Ya instalado |
| OpenCode | Agente con modelo local | Instalador oficial o `brew` (fase 6) |

Lo que antes era global ya no lo es: `uv tool install` se sustituye por `uv run` y el alias de §6.1, y `pre-commit` va como dependencia de desarrollo.

---

## 9. Hoja de ruta por fases

### Fase 0: Cimientos (dos repos, configuración, contrato de datos)

- [x] Convertir este repo en paquete `src/second_brain/` (`[build-system]` con `uv_build`, `[project.scripts]` con `sb` y `sb-mcp`) y eliminar `main.py`.
- [x] `config.py` y `machines.py`: `config.toml`, perfiles de máquina, `.env`, `SB_HOME`, `SB_MACHINE`.
- [x] Modelos pydantic (`Paper`, `Project`, `FullText`, `Classification`) y `library.py` (escritura atómica y determinista).
- [x] `LICENSE` (AGPL-3.0-or-later).
- [x] `sb init RUTA` (esqueleto del repo de datos con `.gitkeep`, `.gitignore`, `.gitattributes`, hook de git con `sb check --fast`), `sb machine init`, `sb doctor`, `sb check`, `sb status`.
- [x] ruff + pytest + pre-commit + CI en el repo de código.
- [x] Esqueleto de documentación (§11).
- [x] Crear los dos repos **privados** en GitHub; en `biblioteca`, `uv add` del paquete por git y comprobar `uv run sb --help`.

**Terminada el 2026-10-04.** Biblioteca en `~/biblioteca` con el código fijado por git en su `uv.lock`; 29 pruebas y CI en verde. Pendiente: llenar `[user].email` en `config.toml` de la biblioteca.

**Terminado cuando:** en `~/biblioteca`, `uv run sb check` pasa sobre una biblioteca vacía, `uv run sb doctor` reconoce la máquina, y la CI del código está en verde.

### Fase 1: Ingesta desde `inbox/`

- [x] Extracción con marcas de página; detección de PDF escaneado → OCR.
- [x] Detección y normalización de DOI e ID de arXiv; metadatos de Crossref con validación del título.
- [x] Deduplicación (hash, DOI, título difuso) y re-vinculación de PDFs.
- [x] Citekeys; movimiento atómico a `pdfs/`; escritura de `papers/` y `fulltext/`.
- [x] `sb ingest` (`--dry-run`, `--doi`, `--json`), `sb show`, `sb text`.
- [x] Pruebas con PDFs sintéticos y respuestas HTTP grabadas (sin red).

**Terminada el 2026-10-04**, con 20 PDFs reales tomados de Zotero:

- Los 17 con DOI quedaron con el DOI correcto, 16 ingeridos y 1 detectado como duplicado exacto. Cinco de ellos estaban adjuntos en Zotero al artículo equivocado, y `sb` los identificó por su contenido.
- Los 3 sin DOI (dos portadas de ResearchGate y una tesis) quedaron en `needs_review`, con título y año aproximados. Su autor y su título definitivos se resuelven al revisarlos (fase 4).
- Repetir la ingesta no cambia nada; volver a soltar los mismos PDFs da 20 duplicados; un PDF borrado de `pdfs/` se re-vincula por hash, sin consultar la red.
- Unos 10 s por PDF en el iMac; ~75 KB de texto por artículo en `library/`.
- Extras: `sb remove`, `--section` reconoce secciones numeradas, `.DS_Store` en `.gitignore`.
- pymupdf4llm queda fijado en 0.3.x: desde 1.27.2 exige onnxruntime, que no tiene binarios para Mac Intel (ADR 0003).

**Terminado cuando:** al ingerir 20 de tus PDFs reales, cada uno queda con el DOI correcto o marcado `needs_review`, no se cuela ningún duplicado, y repetir `sb ingest` no cambia nada.

### Fase 2: Ingesta por DOI y descarga de PDFs

- [x] `sb ingest DOI…`, `--dois`, `--retry`; estado `awaiting_pdf`.
- [x] Acceso abierto (Unpaywall, arXiv).
- [x] Detección de red UNAM por IP pública (`[access].ip_ranges`) y mensaje de OpenVPN interactivo / `needs_vpn`.
- [x] Descarga institucional vía `citation_pdf_url` y enlaces de Crossref; validación `%PDF` + título; reglas de cortesía.
- [x] `sb pdf status/get/open`.

**Terminada el 2026-10-04**, con 20 DOIs de tu Zotero y el OpenVPN activo:

- Solo 4 se descargaron solos: 2 de IOP (enlace de Crossref), 1 de arXiv y 1 de una revista mexicana. Los otros 16 quedaron en `awaiting_pdf` con su motivo.
- Casi todas las editoriales (Elsevier, MDPI, Springer, EDP, ACM, SSRN) bloquean a cualquier cliente que no sea un navegador, aun desde la red UNAM. Esto no depende de la suscripción: son protecciones anti-robots, y no se esquivan. `sb` lo reporta como "la editorial bloquea las descargas automáticas".
- **Decisión del usuario:** no invertir más en descargas automáticas. El flujo principal sigue siendo soltar PDFs en `inbox/`. Para los que esperan PDF, `sb pdf open --awaiting` los abre en el navegador y `sb ingest ~/Downloads/*.pdf` los asocia a su registro.
- Sin `[user].email`, no se consulta Unpaywall.

**Terminado cuando:** con 20 DOIs de editoriales distintas, cada uno termina descargado o en `awaiting_pdf` con un motivo claro; sin VPN se te pide activarlo, y con VPN `--retry` recupera los que tu suscripción cubre.

### Fase 3: Proyectos y BibTeX

- [x] `sb project …` con `kind`, validación de existencia y sugerencia del más parecido.
- [x] `sb bib` (proyecto, claves, `--from-tex`, `sync`) con protección de mayúsculas y limpieza de HTML/MathML.
- [x] Pruebas *golden* del BibTeX.

**Terminada el 2026-10-04.** Con los 18 artículos reales del laboratorio, el `.bib` compila con `elsarticle` + `elsarticle-harv` (BibTeX) y con biblatex + biber. Solo hay avisos de BibTeX para los artículos sin autor, que siguen en `needs_review`. Las pruebas automáticas también compilan con LaTeX cuando está instalado. Limitación: los títulos se guardan como texto plano, así que `CO<sub>2</sub>` de Crossref queda como `{CO2}`, no como `CO$_2$`.

**Terminado cuando:** el `.bib` de un proyecto compila con una plantilla de revista (natbib/BibTeX) y con biblatex/biber, y `sb bib --from-tex` detecta las claves que faltan.

### Fase 4: Procesamiento, figuras y consulta con Claude Code (primer sistema completo)

- [x] Prompt `process.v1` (resumen + clasificación); validación y procedencia.
- [x] Figuras: localizar, renderizar, describir (`figures.v1`), `library/figures/`, `sb figures`.
- [x] Backends `claude` (`claude -p`) y `none`; `sb process` (`--pending`, `--stale`); procesamiento al ingerir.
- [x] Índice SQLite FTS5 con filtros de clasificación; `sb search`, `sb list`, `sb passages`, `sb index`.
- [x] Skills `sb-ingerir`, `sb-consultar`, `sb-proyectos`, `sb-bibtex`; `AGENTS.md`; `sb agents sync`.
- [x] `.claude/settings.json`, hook `SessionStart`, `sb chat claude`.

**Terminada el 2026-10-04**, con 3 PDFs reales de Zotero en una biblioteca de prueba:

- `sb ingest` procesó solo los 3 artículos (unos 3 min en total): resúmenes con cifras y páginas, clasificación correcta (p. ej., experimental, Tuxtla Gutiérrez, MX) y 13, 7 y 5 figuras descritas.
- Preguntado en modo `-p`, el agente respondió solo con la biblioteca y con `[citekey, p. N]`. Creó un proyecto en lenguaje natural con los artículos pertinentes (explicando por qué excluyó uno) y generó su `.bib` con `sb bib`.
- **A tener en cuenta:** Claude Code solo respeta el permiso `uv run sb` de `.claude/settings.json` si la carpeta es "confiable". La primera vez que se abre `sb chat` hay que aceptarlo.
- Pendiente para después: los `needs_review` sin DOI todavía no reciben metadatos sugeridos por el LLM, y la búsqueda es léxica (la semántica es la fase 7).

**Terminado cuando:** `uv run sb ingest` deja artículos resumidos, clasificados y con figuras descritas, sin abrir ningún agente; y desde `uv run sb chat` puedes preguntar "¿qué tengo sobre X en México?", pedir detalles con citas de página, crear un proyecto en lenguaje natural y obtener su `.bib`.

### Fase 5: Traer tu biblioteca existente

- [x] `sb import bib` (`--dry-run`, `--project`) con citekeys conservados y asociación posterior de PDFs.
- [x] Ingesta por partes (`--limit`) de tus PDFs actuales.

**Terminada el 2026-10-04**, con el `.bib` de los 14 artículos que ingirió el usuario (`~/Downloads/biblioteca-14.bib`):

- En una biblioteca nueva, `sb import bib` registró las 14 entradas. Al soltar los PDFs, los 14 se asociaron: 13 por DOI y 1 sin DOI por título. El `.bib` que sale después es idéntico al original.
- Reimportar no duplica nada. Las claves que no sirven como nombre de archivo (estilo Zotero, `Lopez:2019_x`) quedan como alias, y `sb bib` las sigue escribiendo.
- Esquema de datos 2 (`aliases`) con `sb migrate`.

**Terminado cuando:** todas las entradas de tu `.bib` están en la biblioteca, con su PDF asociado cuando lo hay, y tus `.tex` compilan con `sb bib --from-tex`. Puede adelantarse después de la fase 3, dejando el procesamiento para después.

### Fase 6: LLM local, MCP y OpenCode

- [x] Backends `ollama` y `anthropic`; `sb ask`.
- [x] Servidor MCP `sb-mcp` y `opencode.json` (para Claude Code, el MCP se registra a nivel usuario; dentro de la biblioteca Claude ya usa `sb` con las skills).
- [x] `sb chat opencode`, agente `bibliotecario`, `num_ctx` ampliado (variante del modelo en Ollama).
- [ ] Elegir modelos y medir tiempos en el iMac y en la M5; documentar en `docs/maquinas.md`.

**Terminada en lo que se puede probar en el iMac (2026-10-04).** Por decisión del usuario, del modelo local basta con que funcione y la prioridad es Claude.

- Claude: `sb ask` en ~11 s con citas. Desde otro repositorio, Claude Code consultó la biblioteca por MCP sin permisos denegados.
- Local: `sb ask` con gemma4 (8B, CPU) funciona y cita correctamente, en ~5 min.
- `anthropic` solo está probado con un cliente simulado (no hay API key).
- Pendiente en la M5: instalar OpenCode y probar `sb chat opencode`.

**Terminado cuando:** en la M5, sin internet, puedes procesar artículos, buscar, pedir detalles con citas y obtener el BibTeX de un proyecto con OpenCode + Ollama.

### Fase 7: Búsqueda semántica

- [x] Embeddings locales multilingües + `sqlite-vec`; búsqueda híbrida (RRF).
- [x] Conjunto de evaluación: 20–30 preguntas con su artículo esperado; medir recall@5 antes y después.

**Terminada el 2026-10-04.** Embeddings con model2vec (`potion-multilingual-128M`): sin servidor, con solo numpy, sobre Intel y Apple Silicon. Vectores en el mismo índice y similitud con numpy (no hizo falta `sqlite-vec`). Ollama queda como alternativa.

Evaluación con 24 preguntas (la mitad en español, parafraseadas) sobre 18 artículos procesados:

| Modo | recall@1 | recall@5 | MRR |
|---|---|---|---|
| Solo palabras (BM25) | 0.71 | 0.92 | 0.80 |
| Solo significado | 0.75 | 0.96 | 0.85 |
| Híbrido (por defecto) | 0.79 | 0.92 | 0.85 |

Con los resúmenes en español la búsqueda por palabras ya era buena. Los embeddings rescatan las preguntas en español sobre artículos en inglés (p. ej., "zona de confort para viviendas en Japón": lugar 13 con palabras, lugar 1 por significado). Las diferencias son de una o dos preguntas: hay que repetir la evaluación con más artículos antes de afinar los pesos (`index.WEIGHTS`).

**Terminado cuando:** el recall@5 mejora respecto a BM25 solo, sobre todo en preguntas en español.

### Fase 8: Extras (según necesidad)

- [ ] **Pendiente (2026-10-04): retomar la ingesta por DOI con descarga automática.** Funciona, pero casi todas las editoriales bloquean robots (ver fase 2). Por ahora el usuario descarga los PDFs y los suelta en `inbox/`. Al retomarlo: configurar `[user].email` (Unpaywall) y evaluar las APIs oficiales de las editoriales.
- [x] Más campos de clasificación (clima Köppen, tipo de edificación, escala) y `sb process --reclassify`.
- [x] Grafo de citas dentro de la biblioteca: "¿qué artículos muy citados por mi biblioteca me faltan?".
- [x] Alerta de retractaciones en `sb check --retractions` (Crossref publica los datos de Retraction Watch).
- [x] Material suplementario (varios PDFs por artículo).
- [x] Estado de lectura (por leer / leído) y calificación.

**Terminada el 2026-10-05** (salvo la descarga por DOI, que sigue pendiente). En la biblioteca del usuario, `sb refs --missing` ya muestra obras que citan tres de sus artículos (p. ej., Al-Hazmy 2006) y `sb refs --html` genera el grafo interactivo. Los campos de clasificación extra vienen como ejemplos comentados en `config.toml`: se activan cuando el usuario los necesite.

---

## 10. Logística que conviene no olvidar

**PDFs**

- Los PDFs ingeridos se quedan en `pdfs/` de la máquina donde se ingirieron: fuera de git y **sin respaldo, por decisión**. Si se pierden, el texto, las figuras y los metadatos siguen en git, y los que tienen DOI se pueden volver a descargar con `sb pdf get` (los que no tienen DOI no).
- Un PDF pesa ~1–5 MB; su texto completo, ~100 KB. Mil PDFs son unos 2–5 GB, sin problema en el iMac (1.3 TB libres).
- Los modelos de Ollama pesan ~18–20 GB cada uno; conviene revisarlo en la M5.

**Respaldo**

- Todo lo que necesita respaldo está en git (GitHub). Los PDFs no se respaldan.
- El índice no necesita respaldo: es derivado.

**Acceso institucional y legal**

- Las licencias de las editoriales prohíben las descargas masivas o sistemáticas, y cuando las detectan bloquean el acceso de **toda la institución**. Por eso hay pausas, un máximo por ejecución y nunca se intenta evadir un bloqueo.
- Repo de datos **privado** siempre: el texto completo tiene derechos de autor.
- Con el backend `claude`, el texto del artículo se envía a Anthropic. Con `ollama`, nada sale de tu máquina. Para material sensible (borradores, ideas no publicadas), conviene el modo local.

**Git**

- Nunca versionar binarios: ni SQLite, ni embeddings, ni PDFs. Git LFS no conviene para los PDFs.
- Commits pequeños y descriptivos (`ingest: garcia2021thermal, lopez2019ventilation`); `sb ingest --commit` es opcional.

**Dos repos**

- La biblioteca fija la versión del código en su `uv.lock`: actualizar el código nunca rompe los datos sin que lo decidas.
- Si cambias el código, pruébalo con `uv run sb --home ~/biblioteca` desde el repo de código antes de actualizar la biblioteca.
- `sb agents sync` después de actualizar, para que las skills correspondan a la nueva versión.

**Calidad de los datos**

- PDFs escaneados → OCR y flag `ocr` (calidad menor, a revisar).
- La versión del extractor queda registrada: `sb extract --stale` permite re-extraer cuando haya mejores herramientas.
- No todo tiene DOI (normas ASHRAE/ISO, reportes, tesis, libros): el esquema acepta `isbn`, `url`, `arxiv` y metadatos capturados a mano.

**Escritura de artículos (tu caso de uso principal)**

- Con el alias de §6.1: `sb bib --from-tex main.tex -o refs.bib` desde la carpeta del `.tex`.
- MCP a nivel usuario (`claude mcp add --scope user`, con `SB_HOME`): desde el repo de tu artículo, Claude puede consultar la biblioteca y verificar cada `\cite{}`.
- Overleaf: sincronizar por git (en los planes que lo incluyen) o subir el `.bib` generado.

**Mantenibilidad**

- Versionado semántico del código (`sb --version`) y `CHANGELOG.md`; la `schema_version` de los datos va aparte.
- Los prompts son código: versionados, con su número en la procedencia.
- Cada decisión importante se registra como ADR en `docs/decisiones/`.

---

## 11. Documentación del proyecto

| Documento | Repo | Para quién | Contenido |
|---|---|---|---|
| `README.md` | datos | Tú, día a día | Qué es; ingerir (inbox y DOI, VPN); preguntar (`sb chat`, `sb ask`); proyectos; BibTeX; máquina nueva; problemas comunes |
| `README.md` | código | Desarrollo | Instalar para desarrollar, probar con `--home`, publicar una versión, actualizar la biblioteca |
| `docs/uso.md` | código | Referencia | Todos los comandos con ejemplos (lo mismo que `--help`, ampliado) |
| `docs/arquitectura.md` | código | Quien modifique el código (tú, dentro de 6 meses) | Componentes, flujo de datos, módulos, cómo añadir un backend o un campo de clasificación |
| `docs/formato-datos.md` | código | El código y las personas | Especificación de cada archivo de `library/` y de la configuración. Es el contrato que sobrevive al código |
| `docs/maquinas.md` | código | Tú | Perfiles probados, modelos y tiempos medidos por máquina |
| `docs/desarrollo.md` | código | Desarrollo | Entorno, pruebas, lint, migraciones |
| `docs/decisiones/NNNN-*.md` | código | Tú en el futuro | ADRs breves: por qué texto plano, por qué dos repos, por qué citekeys… |
| `AGENTS.md` + skills | datos (generados) | Los agentes | Reglas y flujos operativos |
| `CHANGELOG.md` | código | Todos | Qué cambió en cada versión (programa y esquema) |

- **Idioma:** código, identificadores y docstrings en inglés; documentación de usuario, mensajes de la CLI y skills en español.
- **Regla de mantenimiento:** todo cambio en comandos o en el formato de datos actualiza `docs/` en el mismo commit.

---

## 12. Calidad: pruebas, CI y evaluaciones

- **Unitarias:** normalización de DOI; citekeys (acentos, partículas, colisiones); BibTeX (archivos *golden*); deduplicación; validación de clasificación contra vocabularios; detección de red; serialización determinista (escribir → leer → escribir da un resultado idéntico).
- **Integración:** ingesta completa con PDFs sintéticos y respuestas HTTP grabadas (sin red), incluidas respuestas de editorial que devuelven HTML en lugar de PDF; importación de `.bib` de distintos orígenes (Zotero, JabRef, escrito a mano).
- **CI del código (GitHub Actions):** ruff y pytest en cada push.
- **Repo de datos:** hook de git local con `uv run sb check --fast` (esquema, vocabularios, tamaños, PDFs fuera de git). No requiere CI en GitHub, que necesitaría credenciales para instalar el paquete privado.
- **Evaluaciones del LLM** (fases 6 y 7): preguntas → artículo esperado (recall@k); preguntas de detalle con respuesta conocida para vigilar alucinaciones; una muestra de clasificaciones y de descripciones de figuras revisadas a mano para comparar backends y modelos.

---

## 13. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| DOI equivocado (de una referencia citada en la página 1) | Validar el título contra Crossref; `needs_review` |
| La editorial devuelve una página HTML en lugar del PDF | Validar `%PDF` y título; `awaiting_pdf` con motivo |
| Bloqueo anti-robots aun con VPN | `sb pdf open` + `inbox/`; APIs de minería de texto (fase 8) |
| Bloqueo de la UNAM por descargas excesivas | Pausas, máximo por ejecución, sin descargas masivas |
| La UNAM cambia sus rangos de IP | Configurables en `[access].ip_ranges` |
| Descripción de figura incorrecta | Marcada como generada; cifras del texto con prioridad; cita con figura y página |
| Clasificación equivocada (país, tipo de estudio) | Página de evidencia, `reviewed: false`, corrección con `sb meta --set` |
| Extracción pobre (escaneados, tablas, ecuaciones) | OCR; flags; versión del extractor registrada; re-extracción |
| LLM local lento en el iMac | Backend `claude` para procesar; la M5 para lotes locales; fragmentos en vez de texto completo |
| Alucinaciones en las respuestas | Citas `[citekey, p. N]` obligatorias, solo texto recuperado, evaluaciones |
| Pérdida de PDFs (sin respaldo) | Texto y figuras en git; los que tienen DOI se vuelven a descargar |
| Código y datos desincronizados | Versión fijada en `uv.lock`; `schema_version`; `sb` se niega a escribir datos más nuevos |
| Citekeys rotos en tus `.tex` | Inmutables; conservados al importar un `.bib`; `sb bib --from-tex` avisa de las que faltan |
| Conflictos de merge entre máquinas | Un archivo por artículo; índice fuera de git; `sb sync` |
| Repositorio demasiado grande a largo plazo | Guardia de tamaño; separar `fulltext/` si `library/` pasa de 1 GB |

---

## 14. Respuestas rápidas

- **¿Cómo agrego un proyecto?** `uv run sb project create tesis-doctoral --name "…" --desc "…"`, o pídeselo al agente en `sb chat` ("crea un proyecto para…"). Después: `sb project add tesis-doctoral KEY…` o `sb ingest --project tesis-doctoral`. Ver §5.5.
- **¿Qué es `sb`?** El programa de línea de comandos del proyecto, definido en `pyproject.toml` y ejecutado con `uv run sb`. Ver §6.1.
- **¿`--project` acepta cualquier cosa?** No: solo proyectos existentes. Los tipos de proyecto (`kind`) se definen en `config.toml`. Ver §5.5.
- **¿Qué va en `config.local.toml`?** Ya no existe. Lo de cada máquina va al repo privado en `machines/{nombre}.toml`, y solo los secretos van en `.env`. Ver §3.5.
- **¿`uv run sb --help` da la ayuda?** Sí, y `uv run sb COMANDO --help` da la de cada comando. Ver §6.1.
- **¿Interpreta figuras?** Sí: al ingerir, un modelo con visión describe cada figura y la descripción queda como texto buscable. Ver §5.9.

---

## 15. Decisiones abiertas (con recomendación por defecto)

| # | Pregunta | Estado / recomendación |
|---|---|---|
| D1 | ¿Código y datos en el mismo repositorio o en dos? | **Resuelta:** dos repos; el de datos instala el código desde GitHub con `uv` (§3.1) |
| D2 | Formato del citekey | `apellido + año + primera palabra` (`garcia2021thermal`); los de un `.bib` importado se conservan |
| D3 | Idioma de los resúmenes | Español, con términos técnicos en inglés cuando no haya traducción establecida |
| D4 | ¿Usas Zotero? | **Resuelta:** sin ninguna dependencia de Zotero; `sb import bib` genérico (§5.7) |
| D5 | ¿Dónde viven los PDFs? | **Resuelta:** en `pdfs/`, en local, sin respaldo |
| D6 | ¿Servidor con GPU en el IER? | **Sustituida:** la M5 cubre el uso local pesado; un servidor sería solo otro perfil |
| D7 | ¿BibTeX o BibLaTeX por defecto? | BibTeX (compatibilidad con plantillas de revistas); BibLaTeX como opción |
| D8 | ¿Commit automático al ingerir? | Desactivado por defecto; `--commit` cuando lo pidas |
| D9 | Nombre del comando | `sb` (corto); se cambia en `pyproject.toml` |
| D10 | Nombre y ubicación del repo de datos | **Resuelta:** `biblioteca`, en `~/biblioteca` y en GitHub (privado) |
| D11 | ¿Qué significa "región"? | **Resuelta:** toda la información de ubicación que haya: país, estado/provincia, localidad |
| D12 | ¿Qué chip y cuánta RAM tiene la Mac mini? | **Resuelta:** Intel, 48 GB; usa Claude |
| D13 | ¿PDFs en la nube, locales o borrados? | **Resuelta:** locales (ver D5) |
| D14 | ¿Cómo funciona el acceso remoto de la UNAM? | **Resuelta:** OpenVPN con IP de la UNAM → detección por rangos de IP |
| D15 | ¿Usas Better BibTeX? | **Resuelta:** no aplica; los citekeys vienen del `.bib` exportado |
| D16 | Licencia del código | **Resuelta:** AGPL-3.0-or-later, por PyMuPDF |
| D17 | Respaldo de PDFs | **Resuelta:** sin respaldo |

---

## 16. Bitácora de decisiones

| Fecha | Decisión | Detalle |
|---|---|---|
| 2026-10-04 | Plan inicial | v0.1 |
| 2026-10-04 | v0.2: comentarios del usuario | Dos repos con `uv` + git; ingesta por DOI con acceso institucional y aviso de VPN; nada en segundo plano (`sb chat`, `sb ask`); perfiles por máquina en git y secretos en `.env`; sin instalaciones globales; clasificación (tipo de estudio y ubicación); proyectos explícitos con `kind` y creación en lenguaje natural; `inbox/` y `pdfs/` con `.gitkeep`; migración desde Zotero; política de espacio en disco |

| 2026-10-04 | v0.3: segunda ronda | Sin `ingest.sh`; repos `second-brain` y `biblioteca` creados (privados); Claude en el iMac; ubicación = país, estado/provincia, localidad; PDFs borrados tras extraer (salvo sin DOI); descripción de figuras al ingerir; OpenVPN detectado por IP; migración desde Zotero con números reales |
| 2026-10-04 | v0.4: tercera ronda | Sin dependencia de Zotero (`sb import bib` genérico); Mac mini Intel 48 GB con Claude; licencia MIT con pypdfium2 + pdfplumber en lugar de PyMuPDF; los PDFs ingeridos se conservan en `pdfs/`, locales y sin respaldo |
| 2026-10-04 | v0.5 | De vuelta a PyMuPDF (pymupdf4llm); licencia AGPL-3.0-or-later en lugar de MIT |

| 2026-10-04 | Fase 0 terminada | Paquete `sb` (init, machine, doctor, check, status), esquema v1, CI; biblioteca inicializada con perfil `imac` |

| 2026-10-04 | Fase 1 terminada | `sb ingest`, `show`, `text`, `remove`; probado con 20 PDFs reales |

| 2026-10-04 | Fase 2 terminada | Ingesta por DOI, `awaiting_pdf`, detección de red y OpenVPN, `sb pdf`; casi todas las editoriales bloquean robots y no se insistirá en descargas automáticas |

| 2026-10-04 | Fase 3 terminada | `sb project`, `sb bib` (proyecto, citekeys, `.tex`, `sync`); compila con elsarticle y biblatex |
| 2026-10-04 | Repo de código público | `AltamarMx/second-brain` pasa a público (AGPL-3.0-or-later); `biblioteca` sigue privado |

| 2026-10-04 | Fase 4 terminada | Procesamiento con `claude -p` (resumen, clasificación, figuras), búsqueda FTS5, skills y `sb chat`; probado de punta a punta |

| 2026-10-04 | Fase 5 terminada | `sb import bib` con alias de citekeys; asociación de PDFs por título; esquema 2 |

| 2026-10-04 | Fase 6 (iMac) | Ollama y API de Anthropic como backends, `sb ask`, servidor MCP, OpenCode preparado; la prioridad es Claude; OpenCode pendiente de probar en la M5 |

| 2026-10-04 | Fase 7 terminada | Búsqueda híbrida con embeddings locales (model2vec); `sb eval search`; recall@1 0.71 → 0.79 |

| 2026-10-05 | Fase 8 terminada | Lectura, retractaciones, grafo de citas (con página interactiva), suplementos, campos de clasificación configurables; esquema 3 |

**Próximo paso:** retomar la descarga por DOI (pendiente) cuando el usuario lo pida; probar OpenCode en la M5.
