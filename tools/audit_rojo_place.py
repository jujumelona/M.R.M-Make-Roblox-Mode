"""Audit a real compiled Rojo place for requested content."""
import argparse
import json
from pathlib import Path
from roblox_mod_ai.authored_plan import RobloxAuthoredPlan
from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--place",type=Path,required=True)
    a=parser.parse_args()
    proposal=RobloxAuthoredPlan.from_dict(json.loads(a.plan.read_text(encoding="utf-8"))).proposal
    result=inspect_compiled_place(proposal,a.place)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["passed"] else 1)
