from pathlib import Path
from roblox_mod_ai.api import CompleteRobloxAISession

def test_economy_rules_copied_from_packed_canonical_source(tmp_path: Path):
    sess = CompleteRobloxAISession(output_root=tmp_path)
    sess.plan("코인 수집 상점")
    out=sess.build(source_only=True)
    root=Path(out.project_dir)
    generated=(root/"src/shared/EconomyRules.luau").read_bytes()
    origin=(Path(__file__).resolve().parents[1]/"roblox_mod_ai/economy_rules.luau").read_bytes()
    assert generated == origin
    shop=(root/"src/server/ShopService.server.luau").read_text(encoding="utf-8")
    assert "EconomyRules.canAfford" in shop and "EconomyRules.charge" in shop
    assert out.metadata["acceptance"]["passed"]
