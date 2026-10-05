---
name: sb-ingerir
description: Ingerir artículos en la biblioteca (PDFs de inbox/ o DOIs), resolver los que quedan por revisar y procesarlos. Úsala cuando el usuario diga "ingiere", "agrega estos artículos", "procesa los pendientes" o suelte PDFs en inbox/.
---

# Ingerir artículos

1. Mira qué hay: `uv run sb status --json`.
2. Ingiere: `uv run sb ingest --json` (todo `inbox/`) o `uv run sb ingest DOI1 DOI2 --json`. Si el usuario nombra un proyecto existente, agrega `--project SLUG`.
3. Revisa cada resultado (`outcome`):
   - `ingested`: listo.
   - `review`: DOI dudoso o sin DOI. Muéstrale al usuario el título y `sb show KEY`, y pregúntale el DOI correcto. Si lo da, reingiere ese PDF con `uv run sb ingest RUTA --doi DOI` (el PDF está en `pdfs/KEY.pdf`; primero `uv run sb remove KEY --yes`, que lo deja en `inbox/_eliminados/`).
   - `duplicate`: avísale cuál ya existía.
   - `awaiting`: no hubo PDF. Si el motivo es acceso, pídele que active el VPN y reintenta con `uv run sb ingest --retry --json`; si la editorial bloquea robots, ofrece `uv run sb pdf open --awaiting`.
   - `error` / `offline`: explica el motivo.
4. El procesamiento (resumen, clasificación, figuras) ocurre solo al ingerir si el perfil de la máquina lo indica. Si quedaron pendientes: `uv run sb process --pending --json` (tarda ~1 min por artículo; avisa al usuario).
5. Sugiere proyectos: compara los resúmenes nuevos (`uv run sb show KEY --json`) con `uv run sb project list --json` y propón a cuáles agregarlos. Pregunta antes de hacerlo.
6. Resume: cuántos ingeridos, por revisar, duplicados y sin PDF.
