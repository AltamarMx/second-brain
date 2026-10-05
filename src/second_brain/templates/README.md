# $name

Biblioteca de artículos gestionada con [second-brain](https://github.com/AltamarMx/second-brain).

## Uso diario

```bash
uv run sb --help        # todos los comandos
uv run sb status        # qué hay pendiente
uv run sb check         # validar la biblioteca
uv run sb doctor        # diagnosticar esta máquina
```

## Carpetas

- `library/`: metadatos, resúmenes, texto completo, figuras, notas y proyectos (en git).
- `inbox/`: suelta aquí los PDFs para ingerir (su contenido no va a git).
- `pdfs/`: PDFs ya ingeridos, solo en esta máquina (su contenido no va a git).
- `machines/`: un perfil por computadora.

## Máquina nueva

```bash
git clone <este repo> && cd $name
uv sync
uv run sb machine init
uv run sb doctor
```
