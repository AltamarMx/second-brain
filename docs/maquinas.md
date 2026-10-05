# Máquinas

Perfiles probados y tiempos medidos. Se completa en la fase 6.

| Máquina | Hardware | Backend de procesamiento | Agente | Notas |
|---|---|---|---|---|
| `imac` | Intel i5-8500, 48 GB, macOS 12.7 | `claude` | `claude` | Solo CPU: el modelo local sirve para respuestas cortas |
| Mac mini | Intel, 48 GB | `claude` | `claude` | Igual que el iMac |
| MacBook Pro M5 | Apple Silicon, 64 GB | por decidir | por decidir | Candidata para procesar en local con Ollama |

## Mediciones (2026-10-04)

| Máquina | Tarea | Backend / modelo | Tiempo |
|---|---|---|---|
| `imac` | Procesar un artículo (resumen, clasificación, ~10 figuras) | `claude` (claude-opus-5-5) | ~1 min |
| `imac` | `sb ask` sobre 3 artículos | `claude` | ~11 s |
| `imac` | `sb ask` sobre 3 artículos | `ollama` (gemma4, 8B Q4, solo CPU) | ~5 min |

El modelo local funciona en el iMac pero es lento; para el uso diario en esta máquina conviene Claude. En la M5 queda pendiente medir y probar OpenCode.
