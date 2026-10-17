from pathlib import Path
from roblox_mod_ai.api import CompleteRobloxAISession

def test_roblox_exploit_resistance_and_cross_platform_controls(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집 상점 검투 아레나 리더보드")
    result = session.build(source_only=True)
    assert result.analysis_report.passed
    assert result.metadata["acceptance"]["passed"], result.metadata["acceptance"]
    byname = {m.name:m.code for m in session.authored_plan.proposal.modules}
    shop=byname["ShopService"]
    for term in ('typeof(itemId)', 'PURCHASE_COOLDOWN', 'MAX_SHOP_DISTANCE',
                 'HumanoidRootPart', 'ShopStalls', 'player.UserId'):
        assert term in shop
    combat=byname["CombatSystem"]
    assert "workspace:Raycast(root.Position, targetRoot.Position - root.Position" in combat
    client=byname["CombatController"]
    assert "ContextActionService:BindAction" in client
    assert "Enum.UserInputType.MouseButton1" in client
    assert "Enum.KeyCode.ButtonR2" in client
    assert 'ContextActionService:SetTitle' in client
