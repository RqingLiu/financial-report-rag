"""The production entry cannot revive retired research storage through a legacy import."""

import subprocess
import sys

import pytest

from finrag.serving import cli
from finrag.serving.config import ServingConfig


def test_production_import_does_not_load_research_adapters():
    code = (
        "import sys; import finrag.serving.cli; "
        "assert not any(m.startswith(('finrag.experiments', 'finrag.evaluation')) for m in sys.modules)"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_default_namespace_and_retired_bootstrap(monkeypatch, capsys):
    assert ServingConfig().namespace == "finrag_live_ready"
    monkeypatch.setattr(sys, "argv", ["fr-rag-serve", "bootstrap"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
