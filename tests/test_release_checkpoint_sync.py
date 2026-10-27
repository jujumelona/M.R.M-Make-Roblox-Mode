"""Regression for generated ZIP whose 26 formatted sources diverged from checkpoints."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from roblox_mod_ai.codegen_checkpoint import sync_release_checkpoints


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_post_stylua_checkpoint_matches_packaged_bytes_and_discards_stale_attestation(tmp_path):
    source = tmp_path / "src/server/AccountServer.luau"
    source.parent.mkdir(parents=True)
    before = "local A={};return A"
    after = "local A = {}\\nreturn A\\n"
    source.write_text(before, encoding="utf-8")
    sig = "a" * 64
    source.joinpath()
    checkpoint = tmp_path / "generation_checkpoint.json"
    checkpoint.write_text(json.dumps({
        "schema": "rmm/codegen-checkpoint-v1",
        "modules": { "src/server/AccountServer.luau": {
            "input_sha256": sig,
            "source_sha256": digest(before),
            "semantic_repair_verified": True,
        }},
    }), encoding="utf-8")
    source.write_text(after, encoding="utf-8")
    mod = SimpleNamespace(file_path="src/server/AccountServer.luau")
    report = sync_release_checkpoints(tmp_path, [mod], lambda _: sig)
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))["modules"]
    assert saved[mod.file_path]["source_sha256"] == digest(after)
    assert "semantic_repair_verified" not in saved[mod.file_path]
    assert report["source_digests_updated"] == 1
    report2 = sync_release_checkpoints(tmp_path, [mod], lambda _: sig)
    assert report2["source_digests_updated"] == 0


def test_release_checkpoint_preserves_exact_attestation_only(tmp_path):
    source = tmp_path / "src/client/UI.client.luau"
    source.parent.mkdir(parents=True)
    source.write_text("return {}\\n", encoding="utf-8")
    path = "src/client/UI.client.luau"
    sig = "b" * 64
    (tmp_path / "generation_checkpoint.json").write_text(
        json.dumps({"schema": "rmm/codegen-checkpoint-v1",
                    "modules": {path: {"input_sha256": sig,
                                       "source_sha256": digest("return {}\\n"),
                                       "semantic_repair_verified": True},
                                "src/server/Old.luau": {"input_sha256": sig,
                                                        "source_sha256": "0" * 64}}}),
        encoding="utf-8",
    )
    mod = SimpleNamespace(file_path=path)
    report = sync_release_checkpoints(tmp_path, [mod], lambda _: sig)
    after = json.loads((tmp_path / "generation_checkpoint.json").read_text())["modules"]
    assert list(after) == [path]
    assert after[path]["semantic_repair_verified"] is True
    assert report["semantic_attestations_preserved"] == 1


@pytest.mark.parametrize("unsafe", ["src/../secret.luau", "src/missing.luau", "bad.lua"])
def test_release_checkpoint_rejects_unsafe_or_missing_file(tmp_path, unsafe):
    with pytest.raises(ValueError, match="RELEASE_CHECKPOINT_"):
        sync_release_checkpoints(tmp_path, [
            SimpleNamespace(file_path=unsafe)
        ], lambda _: "c" * 64)
