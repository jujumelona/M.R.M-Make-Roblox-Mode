"""Proposal 40: a truncated AI code review must split scope, never pass by omission."""
from pathlib import Path
from types import SimpleNamespace as NS

from roblox_mod_ai.source_review import review_generated_sources
from roblox_mod_ai.source_repair_cycle import run_source_repair_cycle
from roblox_mod_ai import source_repair_cycle


def fixture(root: Path, count: int = 48):
    module = NS(
        module_id="dyn_ship", name="ShipServer",
        file_path="src/server/ShipServer.luau", kind="server_module",
        code="",
    )
    path = root / module.file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("--!strict\n" + "\n".join(
        f"local fuel{i} = {i}" for i in range(count)
    ) + "\nreturn true\n", encoding="utf-8")
    p = NS(requested_prompt="Construct and launch a fuelled spacecraft",
           modules=[module], game_design={"detailed_implementation_plan": {
               "required_functions": [{"id": "req", "original_request":
                  "Ship fuel and construction must be server-authoritative"}],
               "implementation_modules": [{
                   "name": "ShipServer", "requirements": ["req"],
                   "responsibility": "Create, fuel and launch the ship",
               }],
           }})
    return p, module, path


def test_truncation_splits_until_every_line_is_reviewed_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p, m, path = fixture(tmp_path)

    class Model:
        def __init__(self):
            self.calls = []

        def complete_json(self, **kw):
            self.calls.append(kw)
            lines = kw["prompt"].split("Luau lines:\n", 1)[1].splitlines()
            assert kw["role"] == "analyzer"
            assert kw["json_schema"]["properties"]["findings"]["maxItems"] <= 2
            if len(lines) > 5:
                raise ValueError("Model JSON completion truncated (finish_reason=length)")
            return {"findings": []}

    model = Model()
    result = review_generated_sources(p, tmp_path, model)
    assert result["status"] == "reviewed_no_blockers", result["reason"]
    assert result["fully_covered"]
    assert result["scoped_retries"]
    assert len(model.calls) == result["model_calls"]
    assert result["source_sha256"][m.file_path]
    covered = []
    for record in result["reviewed"]:
        covered += list(range(record["from_line"], record["to_line"] + 1))
    assert sorted(covered) == list(range(1, len(path.read_text().splitlines()) + 1))


def test_unrecoverable_truncation_fails_without_phantom_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p, m, _ = fixture(tmp_path, 2)
    class Broken:
        def complete_json(self, **kw):
            raise ValueError("Model JSON completion truncated (finish_reason=length)")
    result = review_generated_sources(p, tmp_path, Broken())
    assert result["status"] == "failed"
    assert not result["fully_covered"]
    assert "AI_REVIEW_UNRECOVERABLE_OUTPUT" in result["reason"]
    assert m.file_path in result["reason"]


def test_non_output_error_does_not_trigger_repeated_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p, _, _ = fixture(tmp_path)
    class Unavailable:
        calls = 0
        def complete_json(self, **kw):
            self.calls += 1
            raise RuntimeError("analyzer endpoint unavailable")
    model = Unavailable()
    result = review_generated_sources(p, tmp_path, model)
    assert result["status"] == "failed"
    assert not result["fully_covered"]
    assert model.calls == 1


def test_dynamically_named_host_service_requires_generator_fix(tmp_path, monkeypatch):
    p, m, path = fixture(tmp_path, 2)
    monkeypatch.setattr(source_repair_cycle, "generation_scope", lambda _: {
        "modules": [{"module_id": m.module_id,
                     "strategy": "host_declarative_rank_upgrade"}]
    })
    import hashlib
    source = path.read_text(encoding="utf-8")
    report = {"status": "issues_found", "source_sha256": {
        m.file_path: hashlib.sha256(source.encode()).hexdigest()},
        "findings": [{"file": m.file_path, "line": 2,
                      "quote": "local fuel0 = 0", "severity": "blocking",
                      "issue": "Host template defect", "repair": "Fix generator"}]}
    result = run_source_repair_cycle(
        p, tmp_path, NS(), report,
        verify=lambda: (_ for _ in ()).throw(AssertionError("No AI repair")),
        review_again=lambda: (_ for _ in ()).throw(AssertionError("No AI review")),
    )
    assert result["status"] == "blocked"
    assert "generator-level repair" in result["reason"]
    assert path.read_text(encoding="utf-8") == source
