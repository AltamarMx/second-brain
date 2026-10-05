# second-brain

Biblioteca personal de artículos científicos consultable en lenguaje natural con Claude Code u OpenCode (con un LLM local).

Este repositorio contiene **solo el código** (paquete `second_brain`, comando `sb`). Cada biblioteca vive en un repositorio aparte, privado, creado con `sb init`.

## Empezar

```bash
git clone https://github.com/AltamarMx/second-brain && cd second-brain
uv sync
uv run sb --help
uv run sb init ~/biblioteca --email tu-correo@ejemplo.org
```

Los pasos completos están en [docs/uso.md](docs/uso.md).

## Documentación

- [PLAN.md](PLAN.md): diseño, fases y decisiones.
- [docs/uso.md](docs/uso.md): comandos.
- [docs/formato-datos.md](docs/formato-datos.md): especificación de los archivos de una biblioteca.
- [docs/arquitectura.md](docs/arquitectura.md): cómo está construido el código.
- [docs/desarrollo.md](docs/desarrollo.md): pruebas, versiones, cómo contribuir.

## Estado

Fase 0 (cimientos). Ver la hoja de ruta en [PLAN.md](PLAN.md).

## Licencia

AGPL-3.0-or-later (requerida por PyMuPDF). Ver [LICENSE](LICENSE).
