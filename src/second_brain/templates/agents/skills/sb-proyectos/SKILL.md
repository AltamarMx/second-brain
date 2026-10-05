---
name: sb-proyectos
description: Crear proyectos y agregar o quitar artículos en lenguaje natural ("crea un proyecto para mi tesis", "agrega estos artículos al proyecto X", "¿qué artículos tiene mi tesis?").
---

# Proyectos

## Crear

1. Propón al usuario: slug (minúsculas y guiones, p. ej. `tesis-doctoral`), nombre, tipo (uno de los de `[vocab].project_kind` en `config.toml`) y una descripción breve (objetivo, preguntas, palabras clave).
2. **Muestra la orden y espera su confirmación**:
   `uv run sb project create SLUG --name "…" --kind TIPO --desc "…"`
3. Después, ofrece buscar artículos que encajen: `uv run sb search "<palabras clave de la descripción>" --json`.

## Agregar o quitar artículos

- `uv run sb project add SLUG KEY1 KEY2 --note "para qué sirve"`
- `uv run sb project remove SLUG KEY1`
- Si el proyecto no existe, `sb` sugiere el nombre más parecido: confírmalo con el usuario.

## Consultar

- `uv run sb project list --json`
- `uv run sb project show SLUG --json`
