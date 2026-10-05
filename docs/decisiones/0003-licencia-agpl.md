# 0003. Licencia AGPL-3.0-or-later

- **Estado:** aceptada (2026-10-04)

## Contexto

Se prefirió MIT, pero el mejor extractor de PDF disponible en Mac Intel con Python 3.13 es PyMuPDF/pymupdf4llm, que es AGPL-3.0. Las alternativas permisivas (pypdfium2, pdfplumber) dan peor estructura (encabezados, columnas).

## Decisión

Usar pymupdf4llm y publicar el código como AGPL-3.0-or-later.

## Consecuencias

- Quien redistribuya el código, modificado o no, debe hacerlo con su código fuente y la misma licencia.
- El uso personal no tiene restricciones.
