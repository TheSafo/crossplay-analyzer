"""Expose the existing script checks to pytest and Datadog Test Optimization."""

from pathlib import Path
import runpy
import sys

import pytest


@pytest.mark.parametrize("script", ["test_grid_detection.py", "test_score_ocr.py"])
def test_cli_regression(script, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    monkeypatch.setattr(sys, "argv", [script])
    # Keep execution inside pytest so Test Optimization can associate the
    # script's code coverage with this test, including its failure exit status.
    with pytest.raises(SystemExit) as result:
        runpy.run_path(script, run_name="__main__")
    assert result.value.code == 0
