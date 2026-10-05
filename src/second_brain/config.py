"""Library configuration: locating the library, ``config.toml`` and ``.env``.

Precedence for the library location: ``--home`` option, then ``SB_HOME``,
then the first parent of the current directory that contains ``config.toml``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

CONFIG_FILENAME = "config.toml"
ENV_FILENAME = ".env"


class HomeNotFoundError(RuntimeError):
    pass


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserSection(Section):
    email: str | None = None


class LibrarySection(Section):
    summary_language: str = "es"
    process_prompt: str = "process.v1"
    citekey_format: str = "{auth}{year}{word}"


class VocabSection(Section):
    study_type: list[str] = ["experimental", "numerico", "ambos", "teorico", "revision", "otro"]
    project_kind: list[str] = ["tesis", "articulo", "proyecto", "curso", "otro"]


class FiguresSection(Section):
    describe: bool = True


class AccessSection(Section):
    institution: str | None = None
    ip_ranges: list[str] = []
    vpn_hint: str | None = None
    max_downloads_per_run: int = Field(default=30, ge=1)
    seconds_between_downloads: float = Field(default=10, ge=0)


class ChecksSection(Section):
    max_file_mb: float = Field(default=10, gt=0)


class LibraryConfig(Section):
    user: UserSection = UserSection()
    library: LibrarySection = LibrarySection()
    vocab: VocabSection = VocabSection()
    figures: FiguresSection = FiguresSection()
    access: AccessSection = AccessSection()
    checks: ChecksSection = ChecksSection()


def find_home(explicit: Path | None = None, cwd: Path | None = None) -> Path:
    if explicit is not None:
        home = explicit.expanduser().resolve()
        if not (home / CONFIG_FILENAME).is_file():
            raise HomeNotFoundError(f"{home} no es una biblioteca: falta {CONFIG_FILENAME}")
        return home
    env_home = os.environ.get("SB_HOME")
    if env_home:
        return find_home(Path(env_home))
    start = (cwd or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if (directory / CONFIG_FILENAME).is_file():
            return directory
    raise HomeNotFoundError(
        "No encontré la biblioteca (ningún config.toml desde esta carpeta hacia arriba). "
        "Usa --home RUTA, define SB_HOME o crea una con: sb init RUTA"
    )


def load_config(home: Path) -> LibraryConfig:
    with (home / CONFIG_FILENAME).open("rb") as handle:
        return LibraryConfig.model_validate(tomllib.load(handle))


def load_env(home: Path) -> dict[str, str]:
    """Read ``KEY=VALUE`` lines from ``.env``. Real environment variables win."""
    path = home / ENV_FILENAME
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        values[key] = os.environ.get(key, value.strip().strip("'\""))
    return values
