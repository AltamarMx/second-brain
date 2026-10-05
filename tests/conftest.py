import datetime as dt
from pathlib import Path

import pytest

from second_brain.library import Library
from second_brain.models import Paper, Project
from second_brain.scaffold import init_library


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.delenv("SB_HOME", raising=False)
    monkeypatch.setenv("SB_MACHINE", "test-machine")
    # never download a real embedding model in tests; semantic tests inject FakeEmbedder
    monkeypatch.setattr("second_brain.embeddings.get_embedder", lambda profile: None)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "biblioteca"
    init_library(
        path,
        email="test@example.org",
        institution="Ejemplo",
        ip_ranges=["192.0.2.0/24"],
        vpn_hint="Activa el VPN",
    )
    return path


@pytest.fixture
def lib(home: Path) -> Library:
    return Library(home)


def make_paper(citekey: str = "garcia2021thermal", **overrides) -> Paper:
    data = {
        "citekey": citekey,
        "doi": "10.5555/ejemplo.2021.0001",
        "title": "Thermal performance of earth-sheltered dwellings",
        "authors": [{"family": "García", "given": "Ana"}],
        "year": 2021,
        "added": dt.date(2026, 10, 4),
    }
    data.update(overrides)
    return Paper.model_validate(data)


def make_project(slug: str = "tesis-doctoral", **overrides) -> Project:
    data = {"slug": slug, "name": "Tesis doctoral", "created": dt.date(2026, 10, 4)}
    data.update(overrides)
    return Project.model_validate(data)
