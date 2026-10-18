"""Mutation-test actual generated gameplay: regressions must make Lune E2E fail.

This is a code-level behavioral sensitivity test, not a Roblox Studio emulator
or a real-model reliability benchmark.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

def main() -> None:
    root=Path(".rmm-code-e2e").resolve()
    original=Path((root/"location.txt").read_text(encoding="utf-8").strip())
    assert original.is_dir(),original
    relative_server="src/server/CustomPetHatching.server.luau"
    relative_client="src/client/PetHatchController.client.luau"
    source={
        relative_server:(original/relative_server).read_text(encoding="utf-8"),
        relative_client:(original/relative_client).read_text(encoding="utf-8"),
    }
    mutations=(
        ("no_inventory_reward", relative_server, "pet.Parent = inventory",
         "pet.Value = \"Pet\"", "Nearby living player should receive one pet"),
        ("bypass_distance", relative_server,
         "(root.Position - egg.Position).Magnitude > 12", "false",
         "Remote may not grant pet to distant player"),
        ("bypass_dead_check", relative_server,
         "hum.Health <= 0", "false",
         "Dead humanoid may not receive pet"),
        ("no_remote_send", relative_client,
         "remote:FireServer()", "print(remote.Name)",
         "Nearby living player should receive one pet"),
    )
    evidence=[]
    for name,target,needle,replacement,expected in mutations:
        assert source[target].count(needle)==1,(name,source[target])
        staged=root/"mutations"/name
        if staged.exists(): shutil.rmtree(staged)
        for path,body in source.items():
            out=staged/path
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(body.replace(needle,replacement,1) if path==target else body,
                           encoding="utf-8")
        env={**os.environ,"RMM_PET_E2E_PROJECT":str(staged)}
        run=subprocess.run(["lune","run","tests/pet_gameplay_e2e"],
                           env=env,capture_output=True,text=True,timeout=40)
        message=(run.stdout or "")+"\n"+(run.stderr or "")
        assert run.returncode!=0,(name,"Mutant incorrectly passed",message)
        assert expected in message,(name,"Unexpected mutant failure",message[-1800:])
        evidence.append({"mutation":name,"killed":True,
                         "returncode":run.returncode,
                         "expected_behavioral_failure":expected})
        print("EXPECTED FAILURE DETECTED: "+name+" -> "+expected)
    receipt={
        "schema":"rmm/gameplay-mutants-v1",
        "mutations":evidence,
        "mutations_killed":len(evidence),
        "mutations_survived":0,
        "coverage":"deterministic sample gameplay Luau in Lune, not Studio",
    }
    path=root/"gameplay_mutations_receipt.json"
    path.write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding="utf-8")
    print("MUTATION E2E PASS: all intentional behavioral regressions rejected")

if __name__=="__main__":
    main()
