"""Static contract for test instrumentation; does NOT execute Roblox Studio."""
from pathlib import Path


def test_multiplayer_server_checks_actual_state():
    root = Path(__file__).resolve().parents[1] / "studio_tests"
    server = (root / "RMMStudioServer.server.luau").read_text(encoding="utf-8")
    client = (root / "RMMStudioClient.client.luau").read_text(encoding="utf-8")
    assert 'beforePurchaseCoins = coins.Value' in server
    assert 'coins.Value == beforePurchaseCoins - 50' in server
    assert 'humanoid.WalkSpeed >= 24' in server
    assert 'FindFirstChild("speed_boots")' in server
    assert 'secondCoins.Value == secondStartingCoins' in server
    assert 'status:FireClient(p, "buy")' in server
    assert 'report:FireServer({phase="collected"})' in client
    assert 'report:FireServer({phase="purchased"' in client
    assert 'StudioTestService:LeaveTest()' in client
    assert 'StudioTestService:EndTest(value)' in server
