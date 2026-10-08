# Biblioteca de artículos (second-brain)

Este repositorio es una biblioteca personal de artículos científicos. Se maneja con el comando `sb` (`uv run sb --help`). Todo lo que hagas sobre la biblioteca pasa por `sb`; sus comandos aceptan `--json`, úsalo para leer resultados.

## Mapa

- `library/papers/KEY.md`: metadatos (YAML) y resumen de cada artículo.
- `library/fulltext/KEY.md`: texto completo, con `<!-- page N -->` al inicio de cada página.
- `library/figures/KEY.md`: descripciones generadas de las figuras.
- `library/projects/SLUG.md`: proyectos. La membresía está en cada artículo (`projects:`).
- `library/notes/KEY.md`: notas del usuario.
- `inbox/`: PDFs por ingerir. `pdfs/`: PDFs ya ingeridos (solo en esta máquina).

## Reglas

1. **Escribe en `library/` solo mediante `sb`**, salvo `library/notes/` cuando el usuario lo pida. Leer, libremente.
2. **Nunca escribas BibTeX ni metadatos de memoria:** usa `sb bib` y `sb show`.
3. **Responde solo con lo que leíste en esta sesión desde la biblioteca** (resúmenes, pasajes, texto completo, figuras). Nunca completes con conocimiento general; si el usuario lo pide expresamente, ponlo aparte y etiquétalo como tal.
4. **Cada afirmación sobre un artículo lleva su cita** `[citekey, p. N]`. Las cifras tomadas de una figura se citan `[citekey, Fig. 3, p. 5]` y se presentan como aproximadas; si el texto da la cifra, el texto tiene prioridad.
5. Si algo no aparece tras buscarlo, di "El artículo no lo menciona" e indica qué buscaste.
6. Para preguntas en español sobre artículos en inglés, busca también con los términos en inglés.
7. Ante un DOI dudoso, un posible duplicado, la creación de un proyecto o borrar algo, **pregunta antes**.
8. Si una descarga falla por acceso, pide al usuario que active el VPN de su institución; nunca intentes esquivar un bloqueo.
9. No abras PDFs si existe el texto completo.
10. Si un artículo tiene el flag `retracted` o `expression_of_concern` (en `sb show`), **avísalo cada vez que lo menciones o lo cites**.
11. Commits solo cuando el usuario lo pida, con mensajes `ingest: …`, `project: …`, `process: …`.

## Comandos

Se llaman con `uv run sb …`; los que muestran datos aceptan `--json`.

- `sb status`: qué hay pendiente: PDFs en `inbox/`, artículos por estado, proyectos.
- `sb ingest [RUTA|DOI…]`: ingiere `inbox/` (sin argumentos), PDFs o DOIs; `--doi DOI` fija el DOI de un PDF, `--dry-run`.
- `sb process [KEY…]`: resumen, clasificación y figuras con el LLM del perfil; `--pending`, `--force`.
- `sb figures KEY`: vuelve a describir las figuras de un artículo.
- `sb show KEY`: metadatos, clasificación y resumen (con `--json`, también `pdf.sha256`).
- `sb text KEY`: texto completo; `--pages 4-6`, `--section Métodos`, `--supplement s1`.
- `sb search "tema"`: artículos por tema (significado y palabras); `-p SLUG`, `--year 2015..2024`.
- `sb passages "pregunta"`: pasajes con página y sección; `--paper KEY`, `--refs`.
- `sb list`: artículos con filtros, sin tema; `--status needs_review`, `--reading`. Para contar.
- `sb ask "pregunta"`: respuesta con citas sin abrir chat; `--paper KEY`, `-p SLUG`.
- `sb read KEY`: estado de lectura y calificación; `--status leyendo`, `--rating 4`.
- `sb edit KEY`: corrige metadatos sin tocar texto, resumen ni proyectos; `--author`, `--title`, `--year`, `--from-doi DOI`, `--rekey`.
- `sb refs [KEY]`: citas dentro de la biblioteca; `--missing` (obras que te faltan), `--html` (grafo).
- `sb attach KEY PDF`: agrega material suplementario buscable; `--label`.
- `sb remove KEY`: elimina un artículo (ver abajo); `--yes` sin confirmación.
- `sb pdf status`: artículos que esperan PDF o cuyo PDF no está en esta máquina.
- `sb pdf get [KEY…]`: descarga el PDF de artículos ya registrados; `--missing`.
- `sb pdf open KEY`: abre el PDF local o la página del artículo; `--awaiting`.
- `sb project create SLUG`: crea un proyecto; `--name`, `--kind`.
- `sb project add SLUG KEY…`: agrega artículos a un proyecto; `--note`.
- `sb project remove SLUG KEY…`: los quita del proyecto (siguen en la biblioteca).
- `sb project list`: proyectos con su número de artículos; `--all` incluye archivados.
- `sb project show SLUG`: descripción y artículos de un proyecto.
- `sb project archive SLUG`: archiva un proyecto; `--restore` lo reactiva.
- `sb bib`: BibTeX desde los registros; `-p SLUG` o `--from-tex main.tex`, `-o refs.bib`.
- `sb bib sync`: reescribe los .bib de `[bib_outputs]` del perfil de esta máquina.
- `sb import bib ARCHIVO.bib`: registra un .bib conservando sus citekeys (quedan esperando PDF); `--dry-run`.
- `sb check`: valida la biblioteca; `--retractions` consulta retractaciones (usa la red).
- `sb doctor`: revisa que esta máquina tenga todo lo necesario.
- `sb index update`: actualiza el índice de búsqueda con lo que cambió.
- `sb index rebuild`: reconstruye el índice desde cero.
- `sb migrate`: reescribe los registros con la versión actual del esquema.
- `sb init [RUTA]`: crea o completa un repo de datos.
- `sb machine init`: crea el perfil de esta máquina; `--backend`, `--agent`.
- `sb machine show`: qué perfil está activo.
- `sb agents sync`: actualiza este bloque, las skills `sb-*` y `.claude/settings.json`.
- `sb chat [claude|opencode]`: abre el agente en la biblioteca.
- `sb eval search CASOS.jsonl`: mide recall y MRR de la búsqueda.

Opciones completas: `uv run sb <comando> --help`.

## Comportamientos que conviene saber

- El citekey (`{apellido}{año}{palabra}`; `anon` = sin autor, `nd` = sin año) se asigna al ingerir y no cambia solo. `sb edit KEY --rekey` lo regenera desde los metadatos corregidos y deja el anterior en `aliases`: `sb bib` exporta ambos, así que los .tex no se rompen. `sb edit` saca al artículo de `needs_review`.
- `sb remove` borra registro, texto completo, figuras y textos de suplementos; conserva las notas y mueve el PDF local a `inbox/_eliminados/`. Se pierden proyectos, estado de lectura y calificación: anótalos antes.
- Un PDF se asocia a un registro existente por sha256, por DOI o, si el registro aún no tiene PDF, por título parecido (similitud ≥ 93 y año ±1). Si el título extraído del PDF es malo, no se asocia y se crea un registro nuevo.
- `sb ingest PDF --doi DOI` valida el artículo aunque el título del DOI no esté en la página 1 (solo agrega el flag `metadata_mismatch`). En cambio, un PDF que `sb ingest DOI` descarga para un DOI nuevo queda en `needs_review` en ese caso (p. ej. manuscritos con líneas numeradas).
- `sb import bib`: sin DOI usa los campos del .bib; con DOI, los de Crossref/DataCite **sustituyen** a los del .bib (autor, año, tipo…).
- `sb bib` exporta toda tesis como doctoral: `@phdthesis` (en BibLaTeX, `@thesis` con `type = phdthesis`), también las de maestría.

## Flujos

Están en las skills de `.claude/skills/`: `sb-ingerir`, `sb-consultar`, `sb-proyectos` y `sb-bibtex`.
