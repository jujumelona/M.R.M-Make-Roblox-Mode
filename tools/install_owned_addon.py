"""Safely preview/apply an addon to an owned local Rojo project. No publishing."""
import argparse
import json
from pathlib import Path
from roblox_mod_ai.addon_installer import prepare_owned_addon, apply_owned_addon

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon",type=Path,required=True)
    parser.add_argument("--existing-project",type=Path,required=True)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--i-own-this-experience",action="store_true")
    parser.add_argument("--reviewed-player-data",action="store_true")
    a=parser.parse_args()
    if a.apply:
        result=apply_owned_addon(a.addon,a.existing_project,
            i_own_this_experience=a.i_own_this_experience,
            reviewed_player_data=a.reviewed_player_data)
    else:
        result=prepare_owned_addon(a.addon,a.existing_project)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0 if result.get("passed", True) else 1

if __name__=="__main__":
    raise SystemExit(main())
