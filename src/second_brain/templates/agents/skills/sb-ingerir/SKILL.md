---
name: sb-ingerir
description: Ingerir artículos en la biblioteca (PDFs de inbox/ o DOIs), resolver los que quedan por revisar y procesarlos. Úsala cuando el usuario diga "ingiere", "agrega estos artículos", "procesa los pendientes" o suelte PDFs en inbox/.
---

# Ingerir artículos

1. Mira qué hay: `uv run sb status --json`.
2. Ingiere: `uv run sb ingest --json` (todo `inbox/`) o `uv run sb ingest DOI1 DOI2 --json`. Si el usuario nombra un proyecto existente, agrega `--project SLUG`.
3. Revisa cada resultado (`outcome`):
   - `ingested`: listo.
   - `review`: DOI dudoso o sin DOI. Sigue «Resolver needs_review» (abajo).
   - `duplicate`: avísale cuál ya existía.
   - `awaiting`: no hubo PDF. Si el motivo es acceso, pídele que active el VPN y reintenta con `uv run sb ingest --retry --json`; si la editorial bloquea robots, ofrece `uv run sb pdf open --awaiting`.
   - `error` / `offline`: explica el motivo.
4. El procesamiento (resumen, clasificación, figuras) ocurre solo al ingerir si el perfil de la máquina lo indica. Si quedaron pendientes: `uv run sb process --pending --json` (tarda ~1 min por artículo; avisa al usuario).
5. Sugiere proyectos: compara los resúmenes nuevos (`uv run sb show KEY --json`) con `uv run sb project list --json` y propón a cuáles agregarlos. Pregunta antes de hacerlo.
6. Resume: cuántos ingeridos, por revisar, duplicados y sin PDF.

## Resolver needs_review

No hay comando para corregir los metadatos: el artículo se borra y se recrea, y su PDF se vuelve a asociar. Lista los pendientes con `uv run sb list --status needs_review --json`. Pregunta antes de borrar y haz cada operación primero con `--dry-run` (`sb import bib`, `sb ingest`), justo antes de la real; `sb remove` no tiene `--dry-run`: dile al usuario qué se borra (ver `AGENTS.md`).

1. **Lee la primera página:** `uv run sb text KEY --pages 1-2`. Autores, revista, año y DOI suelen estar ahí aunque la extracción de metadatos haya fallado. Propón al usuario lo que encontraste.
2. **Prepara:** guarda de `uv run sb show KEY --json` los `projects`, `reading` y `rating` (se pierden al borrar) y el `pdf.sha256`. El PDF está en `pdfs/KEY.pdf`; si no está en esta máquina, búscalo por ese sha256 en las carpetas que indique el usuario (p. ej. `find ~/Zotero/storage -name '*.pdf' -exec shasum -a 256 {} + | grep SHA256`) y **cópialo, nunca lo muevas**. Escribe la entrada nueva en `.cache/revisar.bib`; su clave es el citekey que quedará: conserva el actual si ya se cita en algún .tex.
3. **Con DOI confirmado por el usuario:** basta `@article{CLAVE, doi = {DOI}}`; Crossref/DataCite completan el resto. En orden: `uv run sb remove KEY --yes`; `uv run sb import bib .cache/revisar.bib`; copia el PDF a `inbox/` (de `inbox/_eliminados/KEY.pdf` o de donde lo encontraste); `uv run sb ingest inbox/ARCHIVO.pdf --doi DOI`. Se asocia por DOI al registro nuevo (`attached`) y queda `needs_processing`; no vuelve a `needs_review`.
4. **Sin DOI:** la entrada lleva los datos completos (`author`, `title`, `year`, `journal`…). El PDF solo se asociará si el título que se extrae de él (el título actual del registro) se parece al nuevo. Compruébalo antes de borrar nada:
   `uv run python -c 'import sys; from rapidfuzz import fuzz; from second_brain.textutil import normalize_for_match as n; print(fuzz.ratio(n(sys.argv[1]), n(sys.argv[2])))' "TÍTULO ACTUAL" "TÍTULO NUEVO"`
   Hace falta 93 o más (`SIMILAR_TITLE`) y que los años no difieran en más de uno. Si no se cumple, **no borres**: explícale al usuario que el PDF no se asociaría y se crearía otro registro. Si se cumple, sigue el orden del paso 3, pero ingiere sin `--doi`; el dry-run de `sb ingest` debe decir `attached` a CLAVE.
5. **Restaura** lo que guardaste: `uv run sb project add SLUG CLAVE`, `uv run sb read CLAVE --status … --rating …`, y `uv run sb process CLAVE` si no se procesó al ingerir. Si algo salió mal y aún no hay commit: `git restore library/`.
