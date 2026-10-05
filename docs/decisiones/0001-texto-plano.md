# 0001. Texto plano como fuente de verdad

- **Estado:** aceptada (2026-10-04)

## Contexto

La biblioteca debe sincronizarse por GitHub entre varias máquinas, sobrevivir al código y ser legible por personas y agentes.

## Decisión

Cada artículo, proyecto, texto completo y conjunto de figuras es un archivo Markdown con frontmatter YAML en `library/`. Cualquier base de datos (índice SQLite, embeddings) es derivada, vive fuera de git y se reconstruye con un comando.

## Consecuencias

- Diffs pequeños y merges casi sin conflictos (un archivo por artículo).
- Los agentes pueden leer y buscar con herramientas comunes (`grep`).
- La serialización debe ser determinista para no generar diffs falsos.
