---
name: sb-consultar
description: Responder preguntas sobre los artículos de la biblioteca ("¿qué tengo sobre X?", "¿qué método usó KEY?", "compara estos artículos", "¿cuántos artículos hay de México?"), siempre con citas de página.
---

# Consultar la biblioteca

Responde **solo** con lo que leas de la biblioteca en esta sesión y cita cada afirmación como `[citekey, p. N]`.

## ¿Qué artículos hablan de X?

1. `uv run sb search "X" --json` (agrega filtros si la pregunta los trae: `--study experimental|numerico|ambos|…`, `--country MX`, `--region`, `--locality`, `--project`, `--year 2015..2024`).
2. Si la pregunta está en español, repite la búsqueda con los términos en inglés y une los resultados.
3. Responde con la lista: citekey, año, título, tipo de estudio y lugar, y su "En una frase".

Para conteos o listados sin tema: `uv run sb list --json` con los filtros, o `uv run sb status --json`.

## Detalles de un artículo

1. `uv run sb show KEY --json` (resumen y clasificación).
2. `uv run sb passages "pregunta" --paper KEY --json` para encontrar los pasajes; o `uv run sb text KEY --pages 4-6` / `--section methods`.
3. Si el artículo es corto, puedes leer `library/fulltext/KEY.md` completo.
4. Para preguntas sobre figuras, lee `library/figures/KEY.md`.
5. Responde con citas `[KEY, p. N]`. Si no aparece: "El artículo no lo menciona (busqué: …)".

## Comparar varios artículos

Obtén pasajes de cada uno y arma una tabla con una cita en cada celda. No rellenes celdas: "no reportado".
