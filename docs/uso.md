# Uso

Referencia de comandos. `uv run sb --help` y `uv run sb COMANDO --help` muestran lo mismo desde la terminal. Los comandos de fases posteriores se añadirán aquí conforme existan.

## Crear una biblioteca

```bash
# desde el repositorio de código
uv run sb init ~/biblioteca \
    --email tu-correo@ejemplo.org \
    --institution "Mi universidad" \
    --ip-range 192.0.2.0/24 \
    --vpn-hint "Activa el VPN de tu institución"

cd ~/biblioteca
uv add "second-brain @ git+https://github.com/AltamarMx/second-brain"
uv run sb machine init      # perfil de esta computadora
uv run sb doctor
```

`sb init` nunca sobrescribe archivos existentes (salvo con `--force`), así que puede correrse sobre una carpeta que ya tiene contenido.

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `sb init RUTA` | Crea o completa un repositorio de datos |
| `sb machine init [--backend B] [--agent A]` | Crea el perfil de esta máquina y activa el hook de git |
| `sb machine show` | Muestra el perfil activo |
| `sb doctor` | Revisa dependencias y configuración de esta máquina |
| `sb check [--fast] [--json]` | Valida la biblioteca |
| `sb status [--json]` | Muestra lo pendiente |

Opciones globales: `--home RUTA` (o la variable `SB_HOME`) y `--version`.

## Usar `sb` desde otra carpeta

Sin instalación global, con un alias en `~/.zshrc`:

```bash
alias sb='SB_HOME=~/biblioteca uv run --project ~/biblioteca sb'
```
