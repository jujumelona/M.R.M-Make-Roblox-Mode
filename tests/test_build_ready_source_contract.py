"""No alternate build-ready route around current source ownership audits."""
from types import SimpleNamespace

from roblox_mod_ai.api import CompleteChatReply


def _reply(schema="rmm/pre-design-rag-v1", *, mode="new_experience"):
    proposal = SimpleNamespace(
        requested_prompt="Author one player action",
        game_design={
            "project_mode": mode,
            "features": {"is_shop": True},
            "dynamic_design": None,
            "pre_design_research": {"schema": schema, "ledger": {}},
        },
    )
    return CompleteChatReply(
        message="draft", approval_hash="not-a-certification",
        authored_plan=SimpleNamespace(proposal=proposal))


def test_legacy_research_schema_cannot_resume_as_build_ready(monkeypatch):
    monkeypatch.setattr("roblox_mod_ai.api.ledger_complete", lambda *a: True)
    assert not _reply(schema="legacy-unsupported").ready_to_build


def test_existing_experience_addon_requires_current_blueprint(monkeypatch):
    monkeypatch.setattr("roblox_mod_ai.api.ledger_complete", lambda *a: True)
    monkeypatch.setattr("roblox_mod_ai.api.audit_implementation_blueprint",
                        lambda *a: {"passed": False})
    monkeypatch.setattr("roblox_mod_ai.api.audit_detailed_plan",
                        lambda *a: {"passed": True})
    assert not _reply(mode="existing_experience_addon").ready_to_build


def test_new_game_and_addon_both_check_detail_ownership(monkeypatch):
    calls = []
    monkeypatch.setattr("roblox_mod_ai.api.ledger_complete", lambda *a: True)
    def blueprint(_proposal):
        calls.append("blueprint")
        return {"passed": True}
    def detailed(_proposal):
        calls.append("detailed")
        return {"passed": False}
    monkeypatch.setattr("roblox_mod_ai.api.audit_implementation_blueprint", blueprint)
    monkeypatch.setattr("roblox_mod_ai.api.audit_detailed_plan", detailed)
    assert not _reply().ready_to_build
    assert not _reply(mode="existing_experience_addon").ready_to_build
    assert calls == ["blueprint", "detailed", "blueprint", "detailed"]
