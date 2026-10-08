# Uso

Referencia de comandos. `uv run sb --help` y `uv run sb COMANDO --help` muestran lo mismo desde la terminal. Los comandos de fases posteriores se añadirán aquí conforme existan.

## Crear una biblioteca

```bash
# desde el repositorio de código
uv run sb init ~/biblioteca \
    --email tu-correo@ejemplo.org \
    --institution "Mi universidad" \
    --ip-range 192.0.2.0/24 \
    --vpn-hint "Activa el VPN de tu institución"

cd ~/biblioteca
uv add "second-brain @ git+https://github.com/AltamarMx/second-brain"
uv run sb machine init      # perfil de esta computadora
uv run sb doctor
```

`sb init` nunca sobrescribe archivos existentes (salvo con `--force`), así que puede correrse sobre una carpeta que ya tiene contenido.

## Actualizar una biblioteca

Cuando hay una versión nueva de `second-brain` en GitHub:

```bash
cd ~/biblioteca
uv sync --upgrade-package second-brain   # trae la versión nueva de sb
uv run sb agents sync                    # AGENTS.md, skills sb-*, .claude/settings.json y OpenCode
uv run sb migrate                        # lleva los registros al esquema actual (no toca los que ya lo están)
uv run sb check
git add -A && git commit -m "agents: actualizar second-brain"
```

`sb agents sync` solo reemplaza lo que está entre las marcas `sb:begin`/`sb:end` de `AGENTS.md`: lo que escribiste fuera del bloque, tus propias skills y tus permisos se conservan. El commit lleva el `uv.lock` nuevo, así que en las otras computadoras basta `git pull && uv sync`.

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `sb init RUTA` | Crea o completa un repositorio de datos |
| `sb machine init [--backend B] [--agent A]` | Crea el perfil de esta máquina y activa el hook de git |
| `sb machine show` | Muestra el perfil activo |
| `sb doctor` | Revisa dependencias y configuración de esta máquina |
| `sb check [--fast] [--json]` | Valida la biblioteca |
| `sb status [--json]` | Muestra lo pendiente |
| `sb ingest [PDFs o DOIs…] [--dois F] [--retry] [--doi D] [--project P] [--dry-run] [--limit N] [--json]` | Ingiere los PDFs de `inbox/`, los PDFs o DOIs indicados, o una lista de DOIs |
| `sb ingest --all [--push]` | Todo seguido: ingerir `inbox/`, procesar lo pendiente, validar y hacer commit de `library/` (y `git push` con `--push`) |
| `sb pdf status [--json]` | Artículos que esperan PDF o cuyo PDF no está en esta máquina |
| `sb pdf get KEY… \| --missing` | Descarga el PDF de artículos registrados |
| `sb pdf open KEY` | Abre el PDF local o la página del artículo en el navegador |
| `sb show KEY [--json]` | Metadatos y resumen de un artículo |
| `sb text KEY [--pages 4-6] [--section S]` | Texto completo, algunas páginas o una sección |
| `sb project create [SLUG] [--name N] [--kind K] [--desc D]` | Crea un proyecto (sin argumentos, pregunta cada dato) |
| `sb project add SLUG KEY… [--note N]` / `remove SLUG KEY…` | Agrega o quita artículos de un proyecto |
| `sb project list [--kind K] [--all]` / `show SLUG` / `archive SLUG [--restore]` | Lista, detalle y archivo de proyectos |
| `sb bib -p SLUG \| --keys K1,K2 \| --from-tex main.tex [-o refs.bib] [--format biblatex] [--strict]` | BibTeX desde los registros |
| `sb bib sync` | Reescribe los `.bib` de `[bib_outputs]` del perfil de la máquina |
| `sb process [KEY…] [--pending] [--stale] [--force] [--no-figures] [--backend B]` | Resumen, clasificación y figuras con el LLM del perfil |
| `sb figures KEY` | Vuelve a describir las figuras de un artículo |
| `sb search "tema" [filtros]` | Artículos por tema, con su "En una frase" y pasajes |
| `sb list [filtros]` | Artículos por filtros, sin tema |
| `sb passages "pregunta" [--paper KEY] [--refs]` | Pasajes con página y sección |
| `sb index update/rebuild` | Índice de búsqueda (se actualiza solo) |
| `sb agents sync` | Instala o actualiza `AGENTS.md`, skills y `.claude/settings.json` |
| `sb chat [claude \| opencode]` | Abre Claude Code (o OpenCode con el modelo local) en la biblioteca |
| `sb ask "pregunta" [--paper KEY] [--backend B]` | Pregunta suelta, respondida con citas, sin abrir chat |
| `sb import bib ARCHIVO.bib [--project P] [--dry-run]` | Registra las entradas de un `.bib` existente, conservando sus citekeys |
| `sb bib --all` | BibTeX de toda la biblioteca |
| `sb migrate` | Actualiza los archivos a la versión actual del esquema |
| `sb read KEY [--status S] [--rating N] [--clear]` | Estado de lectura (por-leer, leyendo, leido) y calificación 1-5 |
| `sb edit KEY [--author A]… [--title T] [--year N] [--from-doi DOI] [--rekey] [--dry-run]` | Corrige metadatos sin tocar texto, resumen ni proyectos |
| `sb attach KEY ARCHIVO.pdf [--label L]` | Agrega material suplementario (su texto se vuelve buscable) |
| `sb refs [KEY] [--missing] [--html [-o RUTA] [--no-open]]` | Citas dentro de la biblioteca y obras que te faltan |
| `sb check --retractions` | Consulta en Crossref retractaciones y correcciones |
| `sb process --reclassify [KEY…]` | Vuelve a clasificar (p. ej., tras agregar campos en `config.toml`) |
| `sb remove KEY [--delete-pdf] [--yes]` | Elimina un artículo (el PDF pasa a `inbox/_eliminados/`) |

Opciones globales: `--home RUTA` (o la variable `SB_HOME`) y `--version`.

## Ingerir PDFs

```bash
cp ~/Downloads/*.pdf inbox/
uv run sb ingest --dry-run     # qué pasaría
uv run sb ingest
```

Para cada PDF, `sb`:

1. Calcula su hash; si ya está en la biblioteca, es un duplicado (a `inbox/_duplicados/`) o, si a esta máquina le faltaba el PDF, lo re-vincula.
2. Extrae el texto con marcas de página (OCR con Tesseract si está escaneado).
3. Busca el DOI en los metadatos del PDF y en sus dos primeras páginas, y lo confirma en Crossref (o DataCite) comprobando que el título aparezca en la página 1.
4. Sin DOI confirmado, busca el título en Crossref. Si tampoco hay suerte, usa lo que dice el PDF. En ambos casos el artículo queda en `needs_review`.
5. Escribe `library/papers/KEY.md` y `library/fulltext/KEY.md`, y lleva el PDF a `pdfs/KEY.pdf`: lo mueve si estaba en `inbox/` y lo copia si viene de otra carpeta (p. ej. `~/Zotero/storage`), que nunca se toca.

| Resultado | Significado |
|---|---|
| `✓` ingerido | DOI confirmado; queda en `needs_processing` |
| `?` por revisar | DOI dudoso o sin DOI (`needs_review`) |
| `=` duplicado | Ya estaba; el PDF va a `inbox/_duplicados/` |
| `↺` re-vinculado | El registro ya existía y esta máquina no tenía su PDF |
| `✗` error | El PDF va a `inbox/_errores/` con un `.motivo.txt` |
| `!` sin conexión | El PDF se queda en `inbox/`; reintenta luego |

Si el DOI detectado es incorrecto, puedes indicarlo: `uv run sb ingest archivo.pdf --doi 10.xxxx/yyyy`. Las respuestas de Crossref se guardan en `.cache/http/`, así que repetir una ingesta no vuelve a consultar la red.

## Ingerir por DOI

```bash
uv run sb ingest 10.1016/j.enbuild.2021.110987 10.3390/en12091732
uv run sb ingest --dois lista.txt     # un DOI por línea; las líneas con # se ignoran
uv run sb ingest --retry              # reintenta los que esperan PDF
```

Para cada DOI, `sb`:

1. Si ya está en la biblioteca con su PDF, no hace nada.
2. Trae los metadatos de Crossref (o DataCite).
3. Busca el PDF en acceso abierto: arXiv y Unpaywall (este necesita `[user].email`).
4. Si no hay, prueba el acceso institucional: comprueba que la IP pública esté en `[access].ip_ranges`. Si no lo está, muestra `[access].vpn_hint` y espera a que presiones Enter (o `s` para saltar). Después busca el PDF en los enlaces que reporta Crossref y en la etiqueta `citation_pdf_url` de la página de la editorial, y comprueba que lo descargado sea un PDF.
5. Con el PDF, sigue como una ingesta normal. Si el PDF no muestra el título del DOI, queda en `needs_review`.
6. Sin PDF, registra el artículo como `awaiting_pdf` (`…` en la salida) con el motivo. Cuando consigas el PDF, suéltalo en `inbox/`: se asocia solo a su registro.

Reglas de cortesía (en `[access]`): una pausa de `seconds_between_downloads` entre peticiones a editoriales y como máximo `max_downloads_per_run` descargas por corrida. Las editoriales que bloquean robots no se intentan esquivar: `sb pdf open KEY` abre el artículo en el navegador para que lo descargues tú.

## Proyectos y BibTeX

```bash
uv run sb project create tesis-doctoral --name "Tesis doctoral" --kind tesis --desc "Confort térmico…"
uv run sb project add tesis-doctoral lopezperez2019adaptive nicol2010derivation --note "Cap. 2"
uv run sb ingest --project tesis-doctoral          # lo que se ingiera ahora entra al proyecto
uv run sb bib -p tesis-doctoral -o ~/tesis/refs.bib
uv run sb bib --from-tex ~/tesis/main.tex -o ~/tesis/refs.bib   # solo lo citado; avisa de lo que falta
```

- `--project` solo acepta proyectos que existan; si escribes mal el nombre, sugiere el más parecido. Los tipos (`--kind`) están en `[vocab].project_kind` de `config.toml`.
- `--from-tex` sigue `\input` e `\include` y reconoce `\cite`, `\citep`, `\citet`, `\parencite`, `\textcite`, `\autocite`, `\nocite`… Con `--strict` termina con error si falta algún citekey.
- `--format bibtex` (por defecto) convierte acentos a LaTeX para máxima compatibilidad (p. ej., `elsarticle`). `--format biblatex` deja UTF-8, para usarse con biber.
- Se protegen con llaves los acrónimos (`{CO2}`, `{ASHRAE}`) y, en títulos con mayúscula solo inicial, los nombres propios (`{México}`), para que el estilo no los pase a minúsculas.
- Para no repetir rutas, declara en el perfil de la máquina:

  ```toml
  [bib_outputs]
  tesis-doctoral = "~/Documents/tesis/refs.bib"
  ```

  y ejecuta `uv run sb bib sync`.

## Procesar: resumen, clasificación y figuras

Al terminar `sb ingest`, cada artículo nuevo se procesa con el backend de `[process].backend` del perfil de la máquina (`claude` usa Claude Code en modo `-p`, con tu suscripción). Tarda alrededor de un minuto por artículo. Usa `--no-process` para dejarlo para después y `uv run sb process --pending` para procesar lo que falte.

- **Resumen** en `library/papers/KEY.md`, con las secciones *En una frase*, *Problema y objetivo*, *Datos y métodos*, *Resultados principales*, *Conclusiones* y *Limitaciones*, y la página de cada dato.
- **Clasificación:** tipo de estudio (`[vocab].study_type`) y sitios estudiados (país, estado o provincia, localidad), con `reviewed: false` hasta que la confirmes.
- **Términos de búsqueda** en español e inglés, en `keywords` (si Crossref no los dio).
- **Figuras** en `library/figures/KEY.md`. Se detectan por su pie ("Fig. 3. …"), se renderiza su página y se describen. Requiere el PDF en `pdfs/`.
- **Metadatos sugeridos**, solo para los artículos que entraron de un PDF sin DOI (título y año aproximados, sin autores, citekey `anon…`): el LLM lee las primeras páginas y propone autores, título, año, tipo, revista, editorial, DOI e ISBN. Quedan en `suggested` sin tocar el registro; `sb show KEY` los muestra y `sb edit KEY --accept --rekey` los aplica. `sb process --pending` los pide también para los artículos ya resumidos.

Todo queda con su procedencia (modelo, versión del prompt, máquina y fecha). Si editas un resumen a mano, `sb process` no lo sobrescribe sin `--force`. `--stale` rehace lo generado con una versión anterior del prompt.

## Buscar

```bash
uv run sb search "ventilación nocturna" --country MX --study experimental
uv run sb list --project tesis-doctoral --year 2015..
uv run sb passages "temperatura de confort" --paper lopezperez2019adaptive
```

Filtros: `--project`, `--study`, `--country` (código ISO), `--region`, `--locality`, `--year` (`2019`, `2015..2024`, `2015..`, `..2020`); `sb list` acepta también `--status`.

La búsqueda es **híbrida**: combina palabras (BM25) y significado (embeddings), así que una pregunta en español encuentra artículos en inglés y sinónimos. `--mode lexical` o `--mode semantic` fuerzan una sola. El índice vive en `.cache/index.sqlite` y se actualiza solo.

Los embeddings se calculan en tu máquina con model2vec (modelo `minishlab/potion-multilingual-128M`, descargado una vez a la caché de Hugging Face). No hace falta servidor ni internet después de la descarga, y no se envía texto a ningún servicio. Se configuran en el perfil de la máquina:

```toml
[embeddings]
provider = "model2vec"   # model2vec (sin servidor) | ollama | none
```

Para medir la calidad de la búsqueda con tus propias preguntas: `uv run sb eval search preguntas.jsonl`, con una línea `{"q": "…", "expected": "citekey"}` por pregunta.

## Conversar: `sb chat`

```bash
uv run sb chat
```

Abre Claude Code en la carpeta de la biblioteca con sus reglas (`AGENTS.md`: responder solo con lo que hay en la biblioteca, siempre con `[citekey, p. N]`) y cuatro skills: `sb-ingerir`, `sb-consultar`, `sb-proyectos` y `sb-bibtex`. La primera vez, Claude Code pide confiar en la carpeta: acéptalo para que pueda usar `uv run sb` sin preguntar.

Ejemplos: "¿qué artículos tengo sobre confort adaptativo en México?", "¿qué temperatura de confort reporta lopezperez2019adaptive?", "crea un proyecto para mi artículo sobre X con lo que encaje y dame el bib".

## Traer una biblioteca existente

```bash
uv run sb import bib mi-biblioteca.bib --dry-run   # qué pasaría
uv run sb import bib mi-biblioteca.bib             # un registro por entrada, esperando PDF
cp carpeta-con-pdfs/*.pdf inbox/ && uv run sb ingest   # cada PDF se asocia a su registro
```

- Sirve cualquier `.bib` (Zotero, JabRef, Mendeley o escrito a mano). Con DOI, los metadatos se toman de Crossref; sin DOI, del `.bib`. Los `keywords` pasan a `tags`.
- **Se conservan los citekeys** para que tus `.tex` sigan compilando. Si una clave no sirve como nombre de archivo (`Lopez:2019_x`, `Garcia2021` con mayúsculas), el artículo recibe un citekey válido (`lopez-2019-x`) y la clave original queda como **alias**. `sb bib` escribe la entrada con las dos claves, y `--from-tex` con la que cite el documento.
- Si el artículo ya estaba en la biblioteca con otra clave, se agrega esa clave como alias.
- Los PDFs se asocian por DOI o, si no tienen, por título, año y primer autor.
- Por proyectos: exporta un `.bib` por grupo o colección e impórtalo con `--project`.

## Pregunta suelta: `sb ask`

```bash
uv run sb ask "¿qué temperatura de confort reportan en clima cálido húmedo?"
uv run sb ask "¿qué software usaron?" --paper lopezperez2019adaptive
```

Busca los resúmenes y pasajes más relevantes (agrega los términos de búsqueda en español e inglés de esos artículos) y le pide al modelo una respuesta con `[citekey, p. N]`. Si el perfil tiene `[llm].model`, usa Ollama; si no, el backend de `[process]` (Claude). `--backend claude|ollama|anthropic` lo fuerza.

## Backends

| Backend | Para qué | Requisitos |
|---|---|---|
| `claude` | Procesar y preguntar con tu suscripción de Claude Code | `claude` instalado |
| `ollama` | Todo en local, sin internet | Ollama abierto y `[llm].model` en el perfil (`model = "gemma4"`); para figuras, un modelo con visión |
| `anthropic` | Lotes grandes con API key | `ANTHROPIC_API_KEY` en `.env` y `uv add "second-brain[anthropic]"` en la biblioteca |
| `none` | Esta máquina no procesa | — |

## La biblioteca desde otros repositorios (MCP)

`sb-mcp` expone la biblioteca como herramientas (`search_papers`, `get_paper`, `search_passages`, `get_fulltext`, `export_bibtex`, `create_project`…). Para usarla desde Claude Code en el repo de cualquiera de tus artículos:

```bash
claude mcp add --scope user second-brain -e SB_HOME=$HOME/biblioteca -- uv run --quiet --project $HOME/biblioteca sb-mcp
```

## OpenCode con modelo local

```bash
uv run sb chat opencode
```

Necesita OpenCode (`brew install opencode`), Ollama abierto y `[llm].model` en el perfil de la máquina. `sb` crea en Ollama una variante del modelo con el contexto de `[llm].num_ctx` (por defecto 32k, que OpenCode necesita para usar herramientas) y abre OpenCode con el agente `bibliotecario`, que solo consulta mediante el servidor MCP.

## Extras

- **Lectura:** `sb read KEY --status leido --rating 4`; luego `sb list --reading por-leer`.
- **Corregir metadatos:** `sb edit KEY --author "Huelsz, Guadalupe" --year 2018 --container "Ingeniería"` cambia solo el registro: el texto completo, el resumen, las figuras, los proyectos y el estado de lectura se quedan. `--author` se repite (sin coma es una organización: `--author IPCC`) y sustituye la lista. `--from-doi DOI` trae los metadatos de Crossref o DataCite, pero solo los valores que traen; lo que escribas en la misma orden gana. Un artículo en `needs_review` queda revisado (`sb edit KEY` sin opciones solo confirma). `--accept` aplica los metadatos que sugirió `sb process`. `--rekey` regenera el citekey desde los metadatos nuevos (o `--key NUEVO`) y renombra registro, texto, figuras, suplementos, notas y PDFs locales; el citekey anterior queda en `aliases` y `sb bib` lo sigue exportando, así que tus `.tex` compilan igual. En otras computadoras, renombra a mano el PDF local.
- **Retractaciones:** cada artículo con DOI guarda las notas que Crossref reporta (retracciones, correcciones, notas de preocupación, con datos de Retraction Watch). `sb check --retractions` vuelve a consultarlas; un artículo retractado queda marcado en `sb show` y los agentes lo advierten al citarlo.
- **Citas:** `sb refs KEY` muestra a quién cita y quién lo cita dentro de tu biblioteca; `sb refs --missing` lista obras que citan dos o más de tus artículos y no tienes; `sb refs --html` guarda el grafo como página interactiva en `.cache/grafo.html` (fuera de git, se regenera en segundos) y la abre en el navegador; `-o RUTA` la guarda en otro lugar y `--no-open` no la abre. La página trae una línea de tiempo: ▶ reproduce el grafo por año de publicación y el control deslizante lo deja en un año; los artículos sin `year` no se animan (están siempre visibles, con borde naranja punteado y en la lista de pendientes) hasta que se complete con `sb edit KEY --year AAAA`. Usa las referencias que publica Crossref.
- **Suplementos:** `sb attach KEY datos.pdf --label "Datos de monitoreo"`. El texto queda en `library/supplements/` y aparece en las búsquedas; el PDF, en `pdfs/KEY--s1.pdf` (copiado si estaba fuera de `inbox/`).
- **Más campos de clasificación:** defínelos en `config.toml` (hay ejemplos comentados: clima Köppen, tipo de edificación, escala), luego `sb process --reclassify` para los artículos ya procesados y filtra con `sb list --field clima=Aw`.

## Usar `sb` desde otra carpeta

Sin instalación global, con un alias en `~/.zshrc`:

```bash
alias sb='SB_HOME=~/biblioteca uv run --project ~/biblioteca sb'
```
