# Issues

Problemas encontrados al usar `sb` sobre una biblioteca real (octubre de 2026). Cada uno lleva dónde ocurre, la evidencia y la propuesta; al resolverlo se marca ✅ y se anota el commit.

| # | Prioridad | Issue | Estado |
|---|---|---|---|
| 1 | alta | `sb ingest RUTA` borra el original fuera de `inbox/` | ✅ resuelto |
| 2 | alta | Un PDF de otra versión impide colocar después el original | ✅ resuelto |
| 3 | alta | No hay forma de corregir metadatos sin DOI | ✅ resuelto |
| 4 | media | Nunca se extraen los autores de PDFs sin DOI | ✅ resuelto |
| 5 | media | El año sale de cualquier número de 4 cifras | ✅ resuelto |
| 6 | media | El título se toma de la letra más grande de la p. 1 | ✅ resuelto |
| 7 | media | Caracteres de fuentes matemáticas (CO₂ → "CCCC") | ✅ resuelto |
| 8 | media | No se aprovechan identificadores de la página (SSRN) | ✅ resuelto |
| 9 | media | Con DOI, Crossref sustituye todo el .bib, incluso con vacíos | ✅ resuelto |
| 10 | media | Los preprints salen como `@article` sin revista | ✅ resuelto |
| 11 | media | Nombres en minúsculas desde Crossref | ✅ resuelto |
| 12 | media | Lo que viene de Zotero pierde sus metadatos y PDFs | ✅ resuelto |
| 13 | media | Mensaje de error de descarga engañoso | ✅ resuelto |
| 14 | media | `sb pdf get --json` informa un estado que no es el del registro | pendiente |
| 15 | media | No hay forma de completar los PDFs locales desde una carpeta | pendiente |
| 16 | baja | El grado de las tesis no se distingue | pendiente |
| 17 | baja | Se pierde el subíndice de CO₂ en BibTeX | pendiente |
| 18 | baja | Las llaves de protección incluyen la puntuación (`{IoT,}`) | pendiente |
| 19 | baja | Prefijos de commit inconsistentes | pendiente |
| 20 | baja | `sb list --reading por-leer` devuelve 0 | pendiente |

## Prioridad alta: riesgo de perder archivos o bloqueos

### 1. `sb ingest RUTA` borra el archivo original aunque esté fuera de `inbox/`

- **Dónde:** `_move_verified` (`ingest/pipeline.py`) copia, verifica y hace `src.unlink()`. Se llama desde cinco lugares sin comprobar de dónde viene el archivo. `_set_aside` sí comprueba que esté en `inbox/`; mover no.
- **Riesgo:** `sb ingest ~/Zotero/storage/ABC/x.pdf` elimina el PDF de Zotero y rompe su adjunto. Se evitó copiando antes a `inbox/` los 59 PDFs tomados de Zotero.
- **Propuesta:** mover solo si el archivo está en `inbox/`; en cualquier otra ruta, copiar.
- **Resolución:** `store_pdf` mueve a `pdfs/` solo lo que viene de `inbox/`; lo de cualquier otra ruta se copia y queda intacto. Vale para `sb ingest` y `sb attach`.

### 2. Un PDF de otra versión impide colocar después el original

- **Qué pasó:** `sb pdf get` guardó otra versión para `universidad2023transferencia` y le puso el flag `pdf_version_mismatch`.
- **Problema:** si después llega el original exacto (mismo sha256 que el registro), `_known_file` ve que `pdfs/KEY.pdf` ya existe, lo trata como `duplicate` y aparta el original. El archivo correcto nunca reemplaza al otro, salvo que alguien borre el local a mano.
- **Propuesta:** si el PDF local tiene otro sha256, reemplazarlo por el original, apartar el anterior y quitar el flag.
- **Resolución:** `_known_file` compara el sha256 del PDF local: si es otra versión, el original la reemplaza, la anterior queda en `inbox/_duplicados/KEY-otra-version.pdf` y se quita `pdf_version_mismatch`.

### 3. No hay forma de corregir los metadatos de un artículo sin DOI

- **Qué pasa:** el único camino es `sb remove`, luego `sb import bib` y luego `sb ingest`. Se pierden el resumen (hay que reprocesar), los proyectos y el estado de lectura.
- **Bloqueo:** el PDF solo vuelve a su registro si el título extraído tiene un parecido de al menos 93. En 3 de los 14 pendientes es imposible: `anon2025bim` da 84.6, `anon2024sin` 18.0 y `anon2022climate` 27.9.
- **Propuesta:** `sb edit KEY --author/--title/--year/--type/--container/--publisher/--genre`, que reescriba el registro sin tocar el texto completo, el resumen ni los proyectos; `--rekey` para cambiar el citekey y guardar el anterior en `aliases`.
- **Resolución:** `sb edit KEY` (`--author`, `--title`, `--year`, `--type`, `--container`, `--publisher`, `--volume`, `--issue`, `--pages`, `--doi`, `--from-doi`, `--dry-run`) reescribe solo el registro y saca al artículo de `needs_review`; como el PDF nunca se separa, desaparece el bloqueo del 93. `--rekey`/`--key` renombran todos los archivos y dejan el citekey anterior en `aliases`. `--genre` llega con el #16.

## Prioridad media: metadatos de PDFs sin DOI (de aquí salen los 15 `anon…`)

### 4. Nunca se extraen los autores

- **Dónde:** la ruta sin DOI de `_resolve` (`ingest/pipeline.py`) solo devuelve título y año, así que `authors` queda vacío y el citekey empieza con `anon`.
- **Evidencia:** en 9 de los 14 pendientes, los autores están claramente en la p. 1 o la p. 2: Ramírez Zúñiga et al., Calixto-Aguirre y Huelsz-Lesbros, Kyaw et al., Huelsz, Rechtman y Rojas, Garza Alejandre, Brito Picciotto y Ashtiani et al.
- **Propuesta:** como `sb process` ya lee el texto con un LLM, que proponga los metadatos (autores, título, año, revista, tipo e identificadores) para los registros con `metadata_source: pdf` y los deje como sugerencia para que el usuario los confirme.
- **Resolución:** `sb process` (y `--pending`, aunque el resumen ya exista) le pide al LLM los metadatos de las primeras 3 páginas de los registros con `metadata_source: pdf`, una sola vez, y los guarda en `suggested` (esquema 4) sin tocar el registro. `sb show` los muestra y `sb edit KEY --accept [--rekey]` los aplica.

### 5. El año sale de cualquier número de 4 cifras

- **Dónde:** `first_year` (`ingest/pipeline.py`) toma el primer número entre 1900 y el año siguiente al actual.
- **Evidencia:** `anon2007consumo` quedó con año 2007 por el texto "ISSN: 2007-3615", cuando el mismo PDF dice 2018.
- **Propuesta:** ignorar los números que siguen a ISSN o ISBN y los teléfonos, y preferir los años cerca de ©, "Received", nombres de mes o la línea de cita de la revista.
- **Resolución:** `publication_year` (antes `first_year`) descarta ISSN, ISBN, teléfonos, DOIs y URLs, y puntúa por contexto: ©, "published" o la línea de cita ("Vol. 19, núm. 3, 2018") ganan; luego fechas (meses, received/accepted, el año más reciente); al final, el primer año suelto.

### 6. El título se toma de la letra más grande de la p. 1

- **Dónde:** `_title_guess` (`ingest/extract.py`).
- **Evidencia:**
  - En portadas toma un aviso: "Preprint not peer reviewed" (SSRN).
  - Toma solo un fragmento del título: "Emissions in 2023" (informe de la IEA).
  - Si la portada solo dice "Summary Report" (menos de 15 caracteres), devuelve "(sin título)".
  - En tesis pega el nombre de la autora: "…A Dissertation Presented DIANA ANDREA BRITO PICCIOTTO".
  - Toma el encabezado de la institución: "UNIVERSIDAD AUTÓNOMA DE NUEVO LEÓN".
- **Propuesta:** revisar las páginas 1 a 3, saltar avisos conocidos, cortar el título en "by", "por", "A Dissertation" o "Tesis", y usar el título de los metadatos del PDF cuando sea razonable.
- **Resolución:** `_title_guess` trabaja por líneas en las páginas 1 a 3: salta avisos (preprint, manuscript, ISSN…) y encabezados de institución, toma el primer bloque contiguo en la letra más grande, corta en "A Dissertation", "Tesis que…", "Presentada por" y en "by/por" solo si sigue un nombre, y acepta títulos cortos de dos palabras. Usa el título de los metadatos del PDF cuando es un título real y aparece en las primeras páginas.

### 7. Caracteres de fuentes matemáticas

- **Evidencia:** el PDF de `ramirezzuniga2025diseno` escribe CO₂ con una fuente matemática y el título salió como "MONITOR DE CCCC". El texto completo también quedó dañado en esa parte.
- **Resolución:** Causa: Word escribe las ecuaciones (CO₂ como fórmula, fuente CambriaMath) con un ToUnicode roto: cada glifo mapea a su carácter dos veces y la O recibe el carácter de la C (`<0725>` y `<0731>` → 𝐶𝐶). `repair_math_tounicode` lo corrige en memoria antes de extraer: quita el duplicado y deduce el carácter de cada glifo por su distancia en gid al bien mapeado (los alfabetos matemáticos son contiguos en la fuente; si hay ambigüedad, el primero usado). `plain_math` pasa 𝑪𝑶𝟐 a CO2 en el texto. Con el PDF real, el título sale "…MONITOR DE CO2 PARA LA CALIDAD…". Limitación: pymupdf4llm a veces coloca la fórmula en otra línea del texto completo.

### 8. No se aprovechan identificadores que vienen en la página

- **Evidencia:** la p. 1 de Kyaw et al. dice `ssrn.com/abstract=4856145`, y el DOI `10.2139/ssrn.4856145` existe en Crossref.
- **Propuesta:** derivar el DOI candidato de los identificadores de SSRN (y de Redalyc, cuando aplique) y validarlo con Crossref.
- **Resolución:** `find_ssrn_doi` convierte `ssrn.com/abstract=N` (o `abstract_id=N`) en el candidato `10.2139/ssrn.N`, que se valida con Crossref como los demás y se prueba antes que los DOIs de las referencias. Con el PDF real de Kyaw et al. da `10.2139/ssrn.4856145`. Redalyc no tiene un DOI derivable de su id (los DOIs, si existen, son de cada revista), así que no aplica.

## Prioridad media: importación y Crossref

### 9. Con DOI, Crossref sustituye todos los campos del .bib, incluso con valores vacíos

- **Dónde:** `import_bib.py` (`{**fields, **crossref_fields(message)}`).
- **Evidencia:** para el Resumen del IPCC (`10.1017/9781009157926.001`), Crossref devuelve 0 autores y año 2023, mientras que el propio documento pide citarlo como "IPCC, 2022". Hubo que dejarlo sin DOI.
- **Propuesta:** combinar solo los valores de Crossref que no estén vacíos, o permitir que ganen los campos del .bib (`--prefer-bib`) conservando el DOI.
- **Resolución:** `sb import bib` combina con `fill`: los valores de Crossref/DataCite ganan solo si no están vacíos (autores, páginas… del .bib se conservan). `--prefer-bib` invierte la prioridad: gana el .bib, Crossref solo llena huecos y se conserva el DOI (`metadata_source: bib+crossref`). El IPCC queda como "IPCC, 2022" con su DOI.

### 10. Los preprints salen como `@article` sin revista

- **Dónde:** el tipo `posted-content` de Crossref se convierte en `article` (`ingest/metadata.py`).
- **Evidencia:** `sb bib` exporta `kyaw2024influences` como `@article` sin `journal`, lo que provoca una advertencia en BibTeX, y no dice que es de SSRN.
- **Propuesta:** un tipo preprint que se exporte como `@misc` o `@online` con `howpublished = {SSRN}`.
- **Resolución:** Tipo `preprint` (Crossref `posted-content`, DataCite `Preprint`) con el servidor (`group-title`: "SSRN") en `container_title`. `sb bib` lo exporta como `@misc` con `howpublished = {SSRN}` y `note = {Preprint}`; un `article` genérico sin revista también sale como `@misc`. Para los ya registrados: `sb edit KEY --from-doi DOI` trae el tipo y el servidor.

### 11. Nombres en minúsculas desde Crossref

- **Evidencia:** "liu, yongping" pasa tal cual a BibTeX.
- **Propuesta:** capitalizar los nombres que vengan completamente en minúsculas.
- **Resolución:** `name_case` capitaliza los nombres que Crossref o DataCite dan completamente en minúsculas ("liu, yongping" → "Liu, Yongping"; guiones, apóstrofos e iniciales incluidos; partículas como "de la" o "van der" quedan en minúscula). Cualquier otra forma se respeta (McDonald, IPCC). Para los ya registrados: `sb edit KEY --from-doi DOI` o `--author`.

### 12. Lo que viene de Zotero pierde sus metadatos

- **Qué pasó:** la colección LCA entró como PDFs sueltos en `inbox/`, aunque Zotero ya tenía el DOI de Kyaw, por ejemplo.
- **Propuesta:** que `sb import bib` lea el campo `file` de las exportaciones de Zotero y Better BibTeX y copie esos PDFs, para traer metadatos y PDF en un solo paso.
- **Además:** avisar cuando el título del PDF no coincida con su registro. En Zotero, el reporte del NREL sobre México cuelga de un artículo que no tiene nada que ver (Arduin 2022).
- **Resolución:** `sb import bib` lee el campo `file` (`desc:ruta:tipo` de Zotero y JabRef, o rutas sueltas de Better BibTeX; relativas al .bib) y copia el primer PDF a su registro en el mismo paso, sin tocar el original. Si la página 1 no muestra el título del registro, no lo asocia y lo avisa (caso NREL/Arduin). Nuevo `sb ingest PDF --key KEY` para asociar un PDF a un registro concreto (lo marca `metadata_mismatch` si el título no coincide).

## Prioridad media: descargas

### 13. Mensaje de error engañoso

- **Dónde:** `fetch/download.py`.
- **Evidencia:** para `huelszlesbros2022importance`, `sb` dice "sin conexión con doi.org: timed out". Pero doi.org responde con un 302 en 0.16 s; el que no responde es revistaingenieria.unam.mx.
- **Propuesta:** informar el servidor de la petición que falló, no el de la primera petición.
- **Resolución:** El mensaje usa el servidor de la petición que falló (`exc.request`, después de las redirecciones), no el de la primera. Si doi.org redirigió bien y lo que no responde es la editorial, el motivo es el nuevo `unreachable` ("revistaingenieria.unam.mx no respondió (ReadTimeout); reintenta más tarde o ábrelo con sb pdf open") y el artículo queda esperando PDF, en lugar de abortar como "sin conexión". Los enlaces fallidos dicen su servidor y el tipo de error.

### 14. `sb pdf get --json` informa un estado que no es el del registro

- **Evidencia:** devuelve `"status": "awaiting_pdf"` para 11 artículos que en realidad siguen como `processed`. Un agente puede malinterpretarlo.

### 15. No hay forma de completar los PDFs locales a partir de una carpeta

- **Qué pasó:** hubo que buscar en Zotero por sha256 con un script para colocar 57 PDFs.
- **Propuesta:** `sb pdf link CARPETA…`, que busque por sha256 y copie a `pdfs/KEY.pdf` sin mover nada; y `sb pdf open --missing`, porque hoy `--awaiting` no incluye los artículos ya procesados cuyo PDF falta en la máquina.

## Prioridad baja: BibTeX, esquema y documentación

### 16. El grado de las tesis no se distingue

- **Dónde:** `bibtex.py` exporta toda tesis como `@phdthesis`.
- **Evidencia:** en la biblioteca hay una de maestría (`anon2016universidad`) y una de licenciatura (`anonndtizacio`).
- **Propuesta:** un campo `genre` o `degree` que permita exportar `@mastersthesis` y, en BibLaTeX, `type = mathesis`.

### 17. Se pierde el subíndice de CO₂

- La normalización Unicode de `encode` (`bibtex.py`) lo convierte en `{CO2}`. **Propuesta:** exportarlo como `CO\textsubscript{2}`.

### 18. Las llaves de protección incluyen la puntuación

- Sale `{IoT,}` en lugar de `{IoT},`.

### 19. Prefijos de commit inconsistentes

- La regla 11 de `AGENTS.md` solo menciona `ingest:`, `project:` y `process:`, pero las instrucciones de actualización (`docs/uso.md`) usan `agents:`.

### 20. `sb list --reading por-leer` devuelve 0

- Los artículos nuevos tienen el estado de lectura en `null`, no en `por-leer`. **Propuesta:** tratar `null` como `por-leer` o documentarlo.
