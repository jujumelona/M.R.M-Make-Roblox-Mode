"""CI code E2E: deterministic model fixture, real tools, no Roblox runtime claim."""
from __future__ import annotations
import hashlib, json, os, sys, zipfile
from pathlib import Path
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place

def main():
    os.environ.update({"RMM_PREDESIGN_LIVE_SEARCH":"0",
                       "RMM_ENABLE_DYNAMIC_DESIGN":"1",
                       "RMM_ENABLE_MODEL_GENERATION":"1",
                       "RMM_ENABLE_MODEL_QUERY_EXPANSION":"0",
                       "RMM_LEGACY_ARCHITECTURE_PROTOCOL":"1"})
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
    from test_dynamic_architecture import LocalGameModel
    root=Path(".rmm-code-e2e").resolve()
    session=CompleteRobloxAISession(output_root=root)
    mock=LocalGameModel()
    session.planner.router=mock
    session.orchestrator.router=mock
    session.orchestrator.code_generator.router=mock
    reply=session.plan("펫 부화")
    assert reply.ready_to_build
    assert "HatchPet" in reply.authored_plan.proposal.game_design["dynamic_design"]["remotes"]

    result=session.build(source_only=False)  # Actual production orchestrator
    tools=result.metadata["tool_results"]
    assert result.metadata["acceptance"]["passed"],result.metadata
    verification=result.metadata["verification"]
    assert verification["schema"]=="rmm/verification-selection-v1"
    assert verification["gameplay_verified"] is False
    assert verification["checks"]["studio_multiplayer"]["status"]=="not_run"
    assert verification["checks"]["studio_structure"]["status"]=="not_run"
    assert verification["checks"]["rojo_build"]["status"]=="passed"
    assert verification["checks"]["compiled_structure"]["status"]=="passed"
    assert verification["checks"]["lune_offline"]["status"]=="not_applicable"
    assert verification["checks"]["luau_compile"]["status"] in ("passed","not_run")
    assert tools.get("wally", {}).get("status") == "not_applicable", tools.get("wally")
    for name in ("stylua","selene","rojo"):
        assert tools.get(name,{}).get("executed") is True,(name,tools.get(name))
        assert tools[name]["success"] is True,(name,tools.get(name))
    if tools.get("luau_analyze",{}).get("executed"):
        assert tools["luau_analyze"]["success"]
    else:
        assert tools["luau_typechecking"]["verified"] is False
    compiled=Path(result.rbxlx_path)
    project=Path(result.project_dir)
    assert compiled.is_file() and compiled.stat().st_size>2000
    inspector=inspect_compiled_place(reply.authored_plan.proposal,compiled,source_root=project)
    assert inspector["passed"],inspector
    checks={c["id"]:c["passed"] for c in inspector["checks"]}
    for name in ("module.RMMServerBootstrap","module.source.RMMServerBootstrap",
                 "module.CustomPetHatching","module.source.CustomPetHatching",
                 "module.PetHatchController","module.source.PetHatchController",
                 "dynamic.remote.HatchPet","dynamic.world.PetEggStand"):
        assert checks.get(name),name

    archive=Path(result.project_zip_path)
    assert archive.is_file()
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist())
        assert "artifact_manifest.json" in names
        assert "verification_report.json" in names
        embedded=json.loads(z.read("verification_report.json"))
        assert embedded==verification
        assert embedded["checks"]["studio_multiplayer"]["status"]=="not_run"
        hashes=json.loads(z.read("artifact_manifest.json"))["source_files"]
        for name,digest in hashes.items():
            assert name in names
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
        assert "src/client/PetHatchController.client.luau" in names
        assert "src/server/CustomPetHatching.luau" in names
        assert "src/server/RMMServerBootstrap.server.luau" in names
        assert "pre_design_research.json" in names
        assert "compiled_place.rbxlx" in names
        assert "local_studio/run_smoke.ps1" in names
        assert hashlib.sha256(z.read("compiled_place.rbxlx")).hexdigest() == hashlib.sha256(compiled.read_bytes()).hexdigest()

    assert result.success is True, "Compiled project must be a successful offline build"
    assert result.metadata["release_status"] == "built_unverified"
    assert result.metadata["runtime"]["passed"] is False
    assert result.metadata["runtime"]["executed"] is False
    assert result.playtest_report.total_tests == 0
    assert not result.playtest_report.passed
    stages=result.work_receipt.to_dict()["stages"]
    assert not any(s["stage"] == "playtest" for s in stages)
    report={
        "schema":"rmm/code-e2e-v1",
        "plan_and_model":"deterministic fixture NOT actual MiMo",
        "actual_toolchain":{k:tools.get(k) for k in
                            ("wally","stylua","selene","luau_analyze","luau_typechecking","rojo")},
        "code_e2e_passed":True,
        "compiled_sources_match":True,
        "source_zip_hashes_checked":True,
        "wiring_checks":{x["id"]:x["passed"] for x in
                         result.metadata["acceptance"]["checks"] if x["id"].startswith("wiring.")},
        "studio_gameplay_passed":False,
        "open_cloud_verified":False,
        "offline_build_success":result.success,
        "production_success":result.success,
        "compiled_place_sha256":hashlib.sha256(compiled.read_bytes()).hexdigest(),
        "stages":stages,
    }
    (root/"location.txt").write_text(str(project),encoding="utf-8")
    out=root/"code_e2e_receipt.json"
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print("CODE E2E PASS; actual Roblox Studio not executed; receipt="+str(out))

if __name__=="__main__":
    main()
