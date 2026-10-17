"""Roblox Open Cloud API client for automated deployment and asset publishing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


class RobloxOpenCloudClient:
    """Interacts with official Roblox Open Cloud APIs."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY", "")
        self.timeout = 30.0

    def publish_place(
        self,
        universe_id: str,
        place_id: str,
        place_file: str | Path,
        version_type: str = "Published",  # "Published" or "Saved"
    ) -> dict[str, Any]:
        """Publishes or saves an .rbxlx or .rbxl place file to Roblox via Open Cloud."""
        if not self.api_key:
            return {
                "success": False,
                "error": "ROBLOX_OPEN_CLOUD_API_KEY not provided. Set env var to publish to Roblox Cloud.",
                "dry_run": True,
            }

        path = Path(place_file).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Place file not found: {path}")

        url = (
            f"https://apis.roblox.com/universes/v1/{universe_id}/places/{place_id}/versions?"
            f"versionType={version_type}"
        )
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/xml" if path.suffix == ".rbxlx" else "application/octet-stream",
        }

        try:
            with open(path, "rb") as f:
                content = f.read()

            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(url, headers=headers, content=content)
                if res.status_code in (200, 201):
                    data = res.json()
                    return {
                        "success": True,
                        "version_number": data.get("versionNumber"),
                        "universe_id": universe_id,
                        "place_id": place_id,
                    }
                return {
                    "success": False,
                    "status_code": res.status_code,
                    "error": res.text,
                }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    def upload_asset(
        self,
        name: str,
        description: str,
        asset_type: str,
        file_path: str | Path,
        creator_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Uploads an asset (Audio, Decal, Model) to Creator Store using Open Cloud Assets API."""
        if not self.api_key:
            return {
                "success": False,
                "error": "ROBLOX_OPEN_CLOUD_API_KEY not configured.",
                "dry_run": True,
            }

        path = Path(file_path).resolve()
        url = "https://apis.roblox.com/assets/v1/assets"
        headers = {"x-api-key": self.api_key}

        # Open Cloud multipart payload
        payload = {
            "assetType": asset_type,
            "displayName": name,
            "description": description,
        }
        if creator_user_id:
            payload["creationContext"] = {"creator": {"userId": creator_user_id}}

        try:
            with open(path, "rb") as f:
                files = {"fileContent": (path.name, f, "application/octet-stream")}
                with httpx.Client(timeout=self.timeout) as client:
                    res = client.post(url, headers=headers, data=payload, files=files)
                    if res.status_code in (200, 201):
                        return {"success": True, "data": res.json()}
                    return {"success": False, "status_code": res.status_code, "error": res.text}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
