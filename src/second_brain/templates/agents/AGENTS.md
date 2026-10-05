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

## Flujos

Están en las skills de `.claude/skills/`: `sb-ingerir`, `sb-consultar`, `sb-proyectos` y `sb-bibtex`.
