# Desarrollo

## Entorno

```bash
git clone https://github.com/AltamarMx/second-brain && cd second-brain
uv sync                      # crea .venv con dependencias y herramientas de desarrollo
uv run pre-commit install    # ruff antes de cada commit (una vez por clon)
```

No hace falta instalar nada globalmente: todo se ejecuta con `uv run`.

## Pruebas y estilo

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

La CI (GitHub Actions) corre lo mismo en cada push a `main`.

## Probar con una biblioteca real

Desde este repositorio, sin tocar el `uv.lock` de la biblioteca:

```bash
uv run sb --home ~/biblioteca check
```

## Publicar una versión y actualizar la biblioteca

1. Subir `version` en `pyproject.toml` y anotar los cambios en `CHANGELOG.md`.
2. Commit, tag (`git tag v0.2.0`) y push con tags.
3. En la biblioteca: `uv lock --upgrade-package second-brain && uv sync`, y commit del `uv.lock`.

## Cambiar el formato de datos

Ver la regla 4 de `docs/arquitectura.md`.
