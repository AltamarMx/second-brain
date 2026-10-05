---
name: sb-bibtex
description: Generar o actualizar el archivo .bib de un proyecto o de un documento LaTeX, y verificar que todos los \cite{} existan en la biblioteca.
---

# BibTeX

Nunca escribas entradas BibTeX a mano: siempre las genera `sb bib` desde los registros.

- De un proyecto: `uv run sb bib -p SLUG -o RUTA/refs.bib`
- De lo citado en un documento: `uv run sb bib --from-tex RUTA/main.tex -o RUTA/refs.bib` (sigue `\input` e `\include`). Reporta los citekeys que falten en la biblioteca y ofrece buscarlos (`sb search`) o ingerirlos.
- Formato: `--format bibtex` (por defecto; plantillas de revista como `elsarticle`) o `--format biblatex` (si el documento usa biblatex/biber).
- Si el perfil de la máquina tiene `[bib_outputs]`: `uv run sb bib sync`.
