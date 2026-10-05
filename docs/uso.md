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

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `sb init RUTA` | Crea o completa un repositorio de datos |
| `sb machine init [--backend B] [--agent A]` | Crea el perfil de esta máquina y activa el hook de git |
| `sb machine show` | Muestra el perfil activo |
| `sb doctor` | Revisa dependencias y configuración de esta máquina |
| `sb check [--fast] [--json]` | Valida la biblioteca |
| `sb status [--json]` | Muestra lo pendiente |
| `sb ingest [PDFs…] [--doi D] [--project P] [--dry-run] [--limit N] [--json]` | Ingiere los PDFs de `inbox/` (o los indicados) |
| `sb show KEY [--json]` | Metadatos y resumen de un artículo |
| `sb text KEY [--pages 4-6] [--section S]` | Texto completo, algunas páginas o una sección |
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
5. Escribe `library/papers/KEY.md` y `library/fulltext/KEY.md`, y mueve el PDF a `pdfs/KEY.pdf`.

| Resultado | Significado |
|---|---|
| `✓` ingerido | DOI confirmado; queda en `needs_processing` |
| `?` por revisar | DOI dudoso o sin DOI (`needs_review`) |
| `=` duplicado | Ya estaba; el PDF va a `inbox/_duplicados/` |
| `↺` re-vinculado | El registro ya existía y esta máquina no tenía su PDF |
| `✗` error | El PDF va a `inbox/_errores/` con un `.motivo.txt` |
| `!` sin conexión | El PDF se queda en `inbox/`; reintenta luego |

Si el DOI detectado es incorrecto, puedes indicarlo: `uv run sb ingest archivo.pdf --doi 10.xxxx/yyyy`. Las respuestas de Crossref se guardan en `.cache/http/`, así que repetir una ingesta no vuelve a consultar la red.

## Usar `sb` desde otra carpeta

Sin instalación global, con un alias en `~/.zshrc`:

```bash
alias sb='SB_HOME=~/biblioteca uv run --project ~/biblioteca sb'
```
