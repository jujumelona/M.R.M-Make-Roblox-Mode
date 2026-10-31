"""Genre-independent routed Roblox Remote -> server source binding regressions."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.remote_ingress_attestation import verify_remote_ingress


def fixture(tmp_path):
    owner = "TransportServer"
    remote = "PerformWork"
    model = SimpleNamespace(
        game_design={"dynamic_design": {
            "remotes": {remote: "RemoteFunction"},
            "host_actions": {remote: {
                "service": owner, "kind": "RemoteFunction", "max_args": 1,
            }},
        }},
        modules=[SimpleNamespace(name=owner, file_path="src/server/TransportServer.luau")]
    )
    folder = tmp_path / "src/server"
    folder.mkdir(parents=True)
    (folder / "TransportServer.luau").write_text(
        "local Service = {}\nfunction Service.handleAction(player, services, ...) "
        "return {success=true} end\nreturn Service\n", encoding="utf-8")
    valid = '''do
    local remote = remotes:WaitForChild("PerformWork", 20)
    if not remote:IsA("RemoteFunction") then error("wrong class") end
    local service = services["TransportServer"]
    remote.OnServerInvoke = function(player, ...)
        if not safeWireArgs(...) then return nil end
        if select("#", ...) > 1 then return nil end
        return service.handleAction(player, services, ...)
    end
end
'''
    (folder / "RMMServerBootstrap.server.luau").write_text(valid, encoding="utf-8")
    return model, valid


def test_single_real_host_action_binding_is_attested(tmp_path):
    proposal, _ = fixture(tmp_path)
    result = verify_remote_ingress(proposal, tmp_path)
    assert result["passed"], result
    assert result["declared_route_count"] == 1
    assert len(result["checked"]) == 1
    assert result["checked"][0]["source_verified"]
    assert result["scope"] == "server_ingress_source_not_studio"


@pytest.mark.parametrize("mutation", [
    'remote.OnServerInvoke = function(player, ...)',
    'return service.handleAction(player, services, ...)',
    'local service = services["TransportServer"]',
    'if not safeWireArgs(...) then return nil end',
    'select("#", ...) > 1',
    'remote:IsA("RemoteFunction")',
])
def test_each_required_link_is_fail_closed(tmp_path, mutation):
    p, body = fixture(tmp_path)
    assert mutation in body
    (tmp_path / "src/server/RMMServerBootstrap.server.luau").write_text(
        body.replace(mutation, "-- REMOVED"),
        encoding="utf-8")
    result = verify_remote_ingress(p, tmp_path)
    assert not result["passed"], result


def test_duplicate_ingress_is_not_accepted(tmp_path):
    p, body = fixture(tmp_path)
    (tmp_path / "src/server/RMMServerBootstrap.server.luau").write_text(
        body + body, encoding="utf-8")
    result = verify_remote_ingress(p, tmp_path)
    assert not result["passed"]
    assert any("duplicated_ingress" in f for f in result["failures"])


def test_wrong_declared_remote_class_cannot_be_papered_over(tmp_path):
    p, _ = fixture(tmp_path)
    p.game_design["dynamic_design"]["remotes"]["PerformWork"] = "RemoteEvent"
    assert not verify_remote_ingress(p, tmp_path)["passed"]


def test_missing_source_owner_is_rejected_even_if_bootstrap_names_it(tmp_path):
    p, _ = fixture(tmp_path)
    (tmp_path / "src/server/TransportServer.luau").unlink()
    result = verify_remote_ingress(p, tmp_path)
    assert not result["passed"]
    assert "server_module_missing_from_disk" in str(result["failures"])


def test_no_host_ingress_is_transparently_not_applicable(tmp_path):
    p, _ = fixture(tmp_path)
    p.game_design["dynamic_design"]["host_actions"] = {}
    result = verify_remote_ingress(p, tmp_path)
    assert result["passed"]
    assert result["status"] == "not_applicable"
    assert result["declared_route_count"] == 0
