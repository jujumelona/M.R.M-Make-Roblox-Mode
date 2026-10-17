"""Official Roblox Creator Store search with authoritative detail verification.

No offline guessed IDs. A creator badge is not a security audit of asset bytes.
"""
from __future__ import annotations

import os
import re
import httpx
from typing import Any

from .spec import RobloxAssetSpec

# Signatures often found in malicious/backdoor Roblox models
BACKDOOR_PATTERNS = [
    re.compile(r"require\s*\(\s*\d{5,}\s*\)", re.IGNORECASE),
    re.compile(r"getfenv\s*\(", re.IGNORECASE),
    re.compile(r"setfenv\s*\(", re.IGNORECASE),
    re.compile(r"loadstring\s*\(", re.IGNORECASE),
    re.compile(r"string\.char\s*\(\s*\d+", re.IGNORECASE),
    re.compile(r"TeleportService:Teleport\s*\(", re.IGNORECASE),
]



ASSET_TYPES = frozenset(("Model", "Audio", "Decal", "MeshPart", "Plugin"))

class RobloxCreatorStoreCatalog:
    SEARCH_URL = "https://apis.roblox.com/toolbox-service/v2/assets:search"
    DETAILS_URL = "https://apis.roblox.com/toolbox-service/v2/assets/"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("ROBLOX_CREATOR_STORE_API_KEY", os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY", ""))
        self.client = client
        self.timeout = 8.0
        self.last_error: str | None = None

    def _headers(self) -> dict[str,str]:
        headers = {"Accept":"application/json"}
        if self.api_key: headers["x-api-key"] = self.api_key
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str,Any]:
        if self.client is None:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        else:
            response = self.client.request(method, url, headers=self._headers(), **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Creator Store returned a non-object")
        return data

    @staticmethod
    def _decode(item: dict[str,Any], target_type: str) -> RobloxAssetSpec | None:
        record = item.get("asset", {})
        if not isinstance(record, dict): return None
        raw_id = str(record.get("id", ""))
        if not raw_id.isdecimal() or int(raw_id) <= 0: return None
        creator = item.get("creator") or {}
        if not isinstance(creator, dict): creator = {}
        name = str(record.get("name") or "")
        if not name: return None
        return RobloxAssetSpec(
            asset_id="rbxassetid://" + raw_id,
            name=name,
            asset_type=target_type,
            creator=str(creator.get("name") or "Unknown"),
            destination_service="SoundService" if target_type == "Audio" else "Workspace",
            description=str(record.get("description") or ""),
            verified=creator.get("hasVerifiedBadge") is True,
        )

    def search(self, query: str, asset_type: str = "Model", limit: int = 5) -> list[RobloxAssetSpec]:
        query = query.strip() if isinstance(query,str) else ""
        if not query: return []
        if asset_type not in ASSET_TYPES: raise ValueError("Unsupported Creator Store type: " + str(asset_type))
        limit = min(max(int(limit),1), 25)
        self.last_error = None
        try:
            # Official recommended POST endpoint; GET with assetType/keyword was incorrect.
            body = {"searchCategoryType":asset_type, "query":query}
            data = self._request("POST", self.SEARCH_URL, json=body)
            records = data.get("creatorStoreAssets") or []
            if not isinstance(records,list): raise ValueError("Missing creatorStoreAssets list")
            out: list[RobloxAssetSpec] = []
            for record in records:
                if len(out) >= limit: break
                if not isinstance(record,dict): continue
                candidate = self._decode(record,asset_type)
                if candidate is None: continue
                # Re-query by ID. Result data alone is NOT a proof that it exists/is usable.
                details = self.get_asset_details(candidate.asset_id)
                if details is None: continue
                if not self.verify_and_sanitize_asset(candidate)["safe"]: continue
                out.append(candidate)
            return out
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            self.last_error = type(exc).__name__ + ": " + str(exc)[:240]
            return []

    def get_asset_details(self, asset_id: str) -> dict[str,Any] | None:
        raw = str(asset_id).removeprefix("rbxassetid://")
        if not raw.isdecimal() or int(raw) <= 0: return None
        try:
            details = self._request("GET",self.DETAILS_URL + raw)
            record = details.get("asset") or {}
            if not isinstance(record,dict) or str(record.get("id")) != raw:
                return None
            return details
        except (httpx.HTTPError,ValueError,TypeError):
            return None

    def search_models(self, query: str, limit: int = 5) -> list[RobloxAssetSpec]:
        return self.search(query,"Model",limit)

    def search_audio(self, query: str, limit: int = 5) -> list[RobloxAssetSpec]:
        return self.search(query,"Audio",limit)

    def verify_and_sanitize_asset(self, asset: RobloxAssetSpec) -> dict[str,Any]:
        flags = [pattern.pattern for pattern in BACKDOOR_PATTERNS if pattern.search(asset.name+" "+asset.description)]
        if not asset.asset_id.removeprefix("rbxassetid://").isdecimal():
            flags.append("invalid asset id")
        if not asset.verified:
            flags.append("Creator lacks verified badge; do not auto-insert")
        return {"asset_id":asset.asset_id, "safe":not flags, "verified":bool(asset.verified),
                "warnings":flags, "sanitized":False,
                "note":"Metadata checks only; contents not audited"}

    def get_asset_injection_code(self, asset: RobloxAssetSpec, sanitize_scripts: bool = True) -> str:
        """Fail-closed: only detail-checked, badged assets should be auto-injected.

        Removing ALL external LuaSourceContainers prevents embedded script execution.
        External Model functionality is not trusted; generated first-party logic is separate.
        """
        if not asset.verified: raise ValueError("Unverified Creator Store asset cannot be auto-injected")
        raw_id = asset.asset_id.removeprefix("rbxassetid://")
        if not raw_id.isdecimal(): raise ValueError("Invalid asset id")
        name = re.sub(r"[^a-zA-Z0-9]","",asset.name)[:40] or "Asset"
        if asset.asset_type == "Audio":
            return (
                "local audio = Instance.new(\"Sound\")\n"
                + f'audio.Name = "{name}"\n'
                + f'audio.SoundId = "rbxassetid://{raw_id}"\n'
                + 'audio.Parent = game:GetService("SoundService")\n'
            )
        if asset.asset_type != "Model": raise ValueError("No safe automatic insertion for asset type")
        if not sanitize_scripts: raise ValueError("Sanitization is mandatory for external models")
        return f"""local function import_{name}()
    local service = game:GetService("InsertService")
    local ok, model = pcall(function() return service:LoadAsset({raw_id}) end)
    if not ok or not model then error("Asset load failed: {raw_id}") end
    -- Must remove all untrusted script containers before parenting to a live service.
    for _, desc in model:GetDescendants() do
        if desc:IsA("LuaSourceContainer") then desc:Destroy() end
    end
    model.Name = "{name}"
    model.Parent = workspace
end
import_{name}()
"""
