# 0003. Licencia AGPL-3.0-or-later

- **Estado:** aceptada (2026-10-04)

## Contexto

Se prefirió MIT, pero el mejor extractor de PDF disponible en Mac Intel con Python 3.13 es PyMuPDF/pymupdf4llm, que es AGPL-3.0. Las alternativas permisivas (pypdfium2, pdfplumber) dan peor estructura (encabezados, columnas).

## Decisión

Usar pymupdf4llm y publicar el código como AGPL-3.0-or-later.

## Consecuencias

- Quien redistribuya el código, modificado o no, debe hacerlo con su código fuente y la misma licencia.
- El uso personal no tiene restricciones.
- pymupdf4llm 1.27.2 y posteriores exigen `pymupdf_layout`, que depende de onnxruntime, sin binarios para Mac Intel. Se fija `pymupdf4llm>=0.3.4,<1` en todas las máquinas (el texto extraído debe ser idéntico en todas). Revisar cuando el iMac y la Mac mini dejen de usarse.
