from __future__ import annotations

import hashlib
from pathlib import Path
import nbformat

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "R.M.M_Make_Roblox_Mode_Colab.ipynb"
EXPECTED_CELL_IDS = (
    "title",
    "configuration",
    "setup",
    "existing-input",
    "registry",
    "plan",
    "build",
    "download",
    "boundaries",
)


def _source_by_id(notebook: nbformat.NotebookNode, cell_id: str) -> str:
    for cell in notebook.cells:
        if cell.get("id") == cell_id:
            return str(cell.source)
    raise SystemExit(f"Missing required Colab cell: {cell_id}")


def validate_notebook() -> str:
    if not NOTEBOOK_PATH.is_file():
        raise SystemExit(f"Missing canonical notebook: {NOTEBOOK_PATH}")

    raw = NOTEBOOK_PATH.read_text(encoding="utf-8")
    notebook = nbformat.reads(raw, as_version=4)
    nbformat.validate(notebook)

    cell_ids = tuple(cell.get("id", "") for cell in notebook.cells)
    if cell_ids != EXPECTED_CELL_IDS:
        raise SystemExit(
            "Unexpected Colab cell layout: "
            f"expected={EXPECTED_CELL_IDS}, actual={cell_ids}"
        )
    if len(cell_ids) != len(set(cell_ids)):
        raise SystemExit("Duplicate Colab cell id")

    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        if cell.get("execution_count") is not None or cell.get("outputs"):
            raise SystemExit(f"Checked-in notebook contains execution state: {cell.id}")
        compile(cell.source, f"<colab:{cell.id}>", "exec")

    colab_name = notebook.metadata.get("colab", {}).get("name")
    if colab_name != NOTEBOOK_PATH.name:
        raise SystemExit(
            f"Notebook metadata name mismatch: expected={NOTEBOOK_PATH.name}, actual={colab_name}"
        )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    digest = validate_notebook()
    print(f"Notebook validation PASSED: sha256={digest[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
