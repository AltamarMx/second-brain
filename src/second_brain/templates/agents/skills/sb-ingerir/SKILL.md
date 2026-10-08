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

Un artículo queda en `needs_review` cuando su DOI es dudoso o no lo tiene (título y año aproximados, sin autores: citekey `anon…`). Se corrige con `sb edit`, que no toca texto, resumen, proyectos ni estado de lectura, y lo saca de `needs_review`. Lista los pendientes con `uv run sb list --status needs_review --json`.

1. **Mira la sugerencia:** si `uv run sb show KEY --json` trae `suggested` (metadatos que el LLM leyó en las primeras páginas al procesar), compárala con `uv run sb text KEY --pages 1-2`; si no la trae, lee esas páginas tú. Autores, revista, año y DOI suelen estar ahí aunque la extracción haya fallado. Propón al usuario los metadatos y pregúntale antes de aplicarlos.
   Si la sugerencia es correcta: `uv run sb edit KEY --accept --rekey --dry-run`, y luego sin `--dry-run`; puedes corregir algún campo en la misma orden (`--year 2018`).
2. **Con DOI confirmado por el usuario:** `uv run sb edit KEY --from-doi DOI --rekey --dry-run`, y luego sin `--dry-run`. Solo aplica los valores que Crossref/DataCite traen; lo que escribas en la misma orden (p. ej. `--year 2022`) tiene prioridad.
3. **Sin DOI:** `uv run sb edit KEY --author "Apellido, Nombre" --author "…" --title "…" --year AAAA --container "…" --type … --rekey --dry-run`, y luego sin `--dry-run`. `--author` sin coma es una organización (`--author IPCC`).
4. **Si los metadatos ya eran correctos:** `uv run sb edit KEY` sin opciones lo marca como revisado.
5. **`--rekey`:** úsalo cuando el citekey quede mal (`anon…`, `…nd…`, año equivocado). El anterior queda como alias, así que los .tex que lo citan siguen funcionando. En las otras computadoras del usuario el PDF local queda con el nombre viejo: allí, `uv run sb pdf link` lo pone en su lugar.
