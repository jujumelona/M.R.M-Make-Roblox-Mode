from __future__ import annotations

from pathlib import Path
from tools.validate_colab_notebook import validate_notebook


def test_colab_notebook_structure_and_syntax() -> None:
    """Verifies that R.M.M_Make_Roblox_Mode_Colab.ipynb satisfies nbformat 4 and executes cleanly."""
    digest = validate_notebook()
    assert isinstance(digest, str)
    assert len(digest) == 64
