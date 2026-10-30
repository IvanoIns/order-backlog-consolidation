"""Fresh seed-42 source data, independent of project output files."""

from pathlib import Path

import pytest

from generator.__main__ import generate
from pipeline.__main__ import run


@pytest.fixture(scope="session")
def generated_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("seed42")
    generate(42, project / "data" / "raw")
    return project


@pytest.fixture(scope="session")
def march_project(generated_project: Path) -> Path:
    assert run(generated_project, "2026-03", "2026-03-31") == 0
    return generated_project
