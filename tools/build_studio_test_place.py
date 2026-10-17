"""Build an instrumented Rojo project from an existing RMM project directory.

Produces a test-only project file. Does NOT alter the canonical release project,
and does not imply StudioTestService has executed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def create_studio_project(project_dir: Path, repo_root: Path) -> Path:
    project_dir = Path(project_dir).resolve()
    repo_root = Path(repo_root).resolve()
    root = json.loads((project_dir / "default.project.json").read_text(encoding="utf-8"))
    tree = root["tree"]
    shared = repo_root / "studio_tests"
    for service, name, source in (
        ("ServerScriptService", "RMMStudioServer", "RMMStudioServer.server.luau"),
        ("StarterPlayer", "RMMStudioClient", "RMMStudioClient.client.luau"),
    ):
        if service == "ServerScriptService":
            destination = tree[service]
        else:
            destination = tree["StarterPlayer"]["StarterPlayerScripts"]
        destination[name] = {"$path": str(shared / source)}
    # Jest and its specs are strictly test-place-only; not included in release Rojo.
    tree["ReplicatedStorage"]["DevPackages"] = {"$path": str(project_dir / "DevPackages")}
    tree["ReplicatedStorage"]["TestSuites"] = {"$path": str(project_dir / "tests")}
    root["name"] = str(root["name"]) + "_STUDIO_E2E_ONLY"
    output = project_dir / "studio-tests.project.json"
    output.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("project_dir", type=Path)
    opts = p.parse_args()
    print(create_studio_project(opts.project_dir, Path(__file__).resolve().parents[1]))
