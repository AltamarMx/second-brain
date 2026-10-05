# 0002. Código y datos en repositorios separados

- **Estado:** aceptada (2026-10-04)

## Contexto

El código debe poder compartirse con otras personas; los datos (texto completo con derechos de autor) son privados. Código y datos deben actualizarse por separado.

## Decisión

`second-brain` contiene solo el código. Cada biblioteca es otro repositorio, creado con `sb init`, que instala el código como dependencia por git con `uv` y fija la versión en su `uv.lock`.

## Consecuencias

- Actualizar el código nunca cambia una biblioteca hasta que esta actualiza su `uv.lock`.
- Nada personal ni institucional en el código: correo, rangos de IP y vocabularios van en `config.toml`.
- Los datos llevan `schema_version` para detectar incompatibilidades entre versiones.
