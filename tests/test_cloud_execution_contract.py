"""Mocked Open Cloud *protocol* tests. Not actual Roblox execution."""
from pathlib import Path

import httpx

from roblox_mod_ai.runtime_verification import OpenCloudRuntimeVerifier
from roblox_mod_ai.spec import RobloxProposal


class Publisher:
    def __init__(self, version=42):
        self.version = version
        self.calls = 0

    def publish_place(self, universe, place, path, version_type):
        self.calls += 1
        assert (universe, place, version_type) == ("111", "222", "Published")
        return {"success": True, "version_number": self.version}


def _run(monkeypatch, tmp_path, state="COMPLETE", results=None, path_override=None,
         output_override=None):
    monkeypatch.setenv("ROBLOX_OPEN_CLOUD_API_KEY", "fake-in-test-only")
    monkeypatch.setenv("ROBLOX_TEST_UNIVERSE_ID", "111")
    monkeypatch.setenv("ROBLOX_TEST_PLACE_ID", "222")
    monkeypatch.setenv("RMM_ALLOW_TEST_PLACE_PUBLISH", "1")
    place_file = tmp_path / "test.rbxlx"
    place_file.write_text("<roblox/>", encoding="utf-8")
    path = path_override or (
        "universes/111/places/222/versions/42/"
        "luau-execution-sessions/session-1/tasks/task-2"
    )
    visited = []

    def handler(request):
        visited.append((request.method, str(request.url)))
        if request.method == "POST":
            assert request.url.path.endswith("/versions/42/luau-execution-session-tasks")
            assert '"script"' in request.content.decode()
            return httpx.Response(200, json={"path": path})
        if request.method == "GET":
            assert request.url.path.endswith("/session-1/tasks/task-2")
            return httpx.Response(200, json={
                "path": path, "state": state,
                "output": ({"results": [True] if results is None else results}
                           if output_override is None else output_override),
            })
        raise AssertionError("Unexpected request")

    publisher = Publisher()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = OpenCloudRuntimeVerifier(
            client=client, publisher=publisher, poll_interval=0, max_polls=2
        ).run(RobloxProposal(
            requested_prompt="coins", game_title="Game", description="Mock only",
            game_design={}, modules=[]
        ), place_file)
    return result, visited, publisher


def test_completed_true_is_only_mock_protocol_success(monkeypatch, tmp_path):
    result, visited, publisher = _run(monkeypatch, tmp_path)
    assert result["passed"] and result["executed"]
    assert publisher.calls == 1
    assert [method for method, _ in visited] == ["POST", "GET"]
    assert result["scope"] == "server_smoke_and_datastore_only"


def test_task_failed_not_approved(monkeypatch, tmp_path):
    result, _, _ = _run(monkeypatch, tmp_path, state="FAILED")
    assert not result["passed"] and result["executed"]


def test_complete_without_true_result_not_approved(monkeypatch, tmp_path):
    result, _, _ = _run(monkeypatch, tmp_path, results=[False])
    assert not result["passed"] and result["executed"]


def test_reject_wrong_task_path_before_get(monkeypatch, tmp_path):
    result, visited, _ = _run(monkeypatch, tmp_path, path_override="https://invalid.example/x")
    assert not result["passed"] and not result["executed"]
    assert [method for method, _ in visited] == ["POST"]


def test_missing_optin_skips_publishing(monkeypatch, tmp_path):
    monkeypatch.delenv("RMM_ALLOW_TEST_PLACE_PUBLISH", raising=False)
    result, publisher = None, Publisher()
    with httpx.Client(transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(
        AssertionError("Network should not be called")
    ))) as client:
        result = OpenCloudRuntimeVerifier(client=client, publisher=publisher).run(
            RobloxProposal(requested_prompt="", game_title="X", description="", game_design={}, modules=[]),
            tmp_path / "missing.rbxlx",
        )
    assert not result["passed"] and not result["executed"]
    assert publisher.calls == 0


def test_malformed_cloud_execution_output_never_becomes_success(monkeypatch, tmp_path):
    result, _, _ = _run(
        monkeypatch, tmp_path, state="COMPLETE", output_override=[]
    )
    assert result["passed"] is False
    assert result["executed"] is True
    assert result["results"] is None


def test_invalid_test_place_publisher_response_is_handled_without_exception(
        monkeypatch, tmp_path):
    monkeypatch.setenv("ROBLOX_OPEN_CLOUD_API_KEY", "fake-in-test-only")
    monkeypatch.setenv("ROBLOX_TEST_UNIVERSE_ID", "111")
    monkeypatch.setenv("ROBLOX_TEST_PLACE_ID", "222")
    monkeypatch.setenv("RMM_ALLOW_TEST_PLACE_PUBLISH", "1")
    place = tmp_path / "test.rbxlx"
    place.write_text("<roblox/>", encoding="utf-8")

    class BrokenPublisher:
        def publish_place(self, *args, **kwargs):
            return ["not a valid publish receipt"]

    with httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(
            AssertionError("No cloud execution should be attempted")
        )
    )) as client:
        result = OpenCloudRuntimeVerifier(
            client=client, publisher=BrokenPublisher()
        ).run(
            RobloxProposal(requested_prompt="", game_title="X",
                           description="", game_design={}, modules=[]),
            place,
        )
    assert not result["passed"] and not result["executed"]
    assert "non-object" in result["reason"]
