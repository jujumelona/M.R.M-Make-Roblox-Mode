"""Roblox Engine API catalog and reference index for small AI models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RobloxAPIDoc:
    class_name: str
    member_type: str  # "Method", "Event", "Property", "Callback"
    member_name: str
    signature: str
    description: str
    example: str = ""
    security: str = "None"  # None, ServerOnly, ClientOnly, RobloxScriptSecurity


# Indexed Roblox Engine API documentation for small AI tool queries
ROBLOX_API_DOCS: list[RobloxAPIDoc] = [
    # DataStoreService
    RobloxAPIDoc(
        class_name="DataStoreService",
        member_type="Method",
        member_name="GetDataStore",
        signature='GetDataStore(name: string, scope: string?): GlobalDataStore',
        description="Returns the DataStore instance with the given name.",
        example='local DataStoreService = game:GetService("DataStoreService")\nlocal playerStore = DataStoreService:GetDataStore("PlayerData_v1")',
        security="ServerOnly",
    ),
    RobloxAPIDoc(
        class_name="GlobalDataStore",
        member_type="Method",
        member_name="GetAsync",
        signature='GetAsync(key: string): (any, DataStoreKeyInfo?)',
        description="Reads value for the given key from DataStore. MUST be wrapped in pcall.",
        example='local success, data = pcall(function()\n    return playerStore:GetAsync("User_" .. player.UserId)\nend)',
        security="ServerOnly",
    ),
    RobloxAPIDoc(
        class_name="GlobalDataStore",
        member_type="Method",
        member_name="SetAsync",
        signature='SetAsync(key: string, value: any): string',
        description="Writes value for given key to DataStore. MUST be wrapped in pcall with retry.",
        example='local success, err = pcall(function()\n    playerStore:SetAsync("User_" .. player.UserId, dataTable)\nend)',
        security="ServerOnly",
    ),
    # Players
    RobloxAPIDoc(
        class_name="Players",
        member_type="Event",
        member_name="PlayerAdded",
        signature='PlayerAdded:Connect(function(player: Player) ... end)',
        description="Fires when a player joins the game server. Ideal for loading stats and character spawning.",
        example='Players.PlayerAdded:Connect(function(player)\n    print("Player joined: " .. player.Name)\nend)',
        security="None",
    ),
    RobloxAPIDoc(
        class_name="Players",
        member_type="Event",
        member_name="PlayerRemoving",
        signature='PlayerRemoving:Connect(function(player: Player) ... end)',
        description="Fires when a player leaves the server. Ideal for saving session data to DataStore.",
        example='Players.PlayerRemoving:Connect(function(player)\n    savePlayerData(player)\nend)',
        security="None",
    ),
    RobloxAPIDoc(
        class_name="Players",
        member_type="Property",
        member_name="LocalPlayer",
        signature='LocalPlayer: Player',
        description="The client's own Player object. Only accessible in LocalScripts / client context.",
        example='local player = game:GetService("Players").LocalPlayer',
        security="ClientOnly",
    ),
    # RemoteEvent
    RobloxAPIDoc(
        class_name="RemoteEvent",
        member_type="Method",
        member_name="FireServer",
        signature='FireServer(...: any)',
        description="Fires the RemoteEvent to the server from a LocalScript. Server receives (player, ...).",
        example='local attackRemote = ReplicatedStorage.Remotes.AttackRequest\nattackRemote:FireServer(targetPart)',
        security="ClientOnly",
    ),
    RobloxAPIDoc(
        class_name="RemoteEvent",
        member_type="Event",
        member_name="OnServerEvent",
        signature='OnServerEvent:Connect(function(player: Player, ...: any) ... end)',
        description="Fires on the server when a client calls FireServer. First argument is ALWAYS the calling Player.",
        example='attackRemote.OnServerEvent:Connect(function(player, targetPart)\n    -- Validate distance and cooldown on server!\nend)',
        security="ServerOnly",
    ),
    RobloxAPIDoc(
        class_name="RemoteEvent",
        member_type="Method",
        member_name="FireClient",
        signature='FireClient(player: Player, ...: any)',
        description="Fires the RemoteEvent from the server to a specific player's client.",
        example='damageRemote:FireClient(player, damageAmount)',
        security="ServerOnly",
    ),
    RobloxAPIDoc(
        class_name="RemoteEvent",
        member_type="Method",
        member_name="FireAllClients",
        signature='FireAllClients(...: any)',
        description="Fires the RemoteEvent from the server to all connected clients.",
        example='announcementRemote:FireAllClients("Arena match started!")',
        security="ServerOnly",
    ),
    # TweenService
    RobloxAPIDoc(
        class_name="TweenService",
        member_type="Method",
        member_name="Create",
        signature='Create(instance: Instance, tweenInfo: TweenInfo, propertyTable: {[string]: any}): Tween',
        description="Creates a Tween that interpolates properties of the instance smoothly.",
        example='local TweenService = game:GetService("TweenService")\nlocal info = TweenInfo.new(0.5, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)\nlocal tween = TweenService:Create(uiFrame, info, { Position = UDim2.new(0.5, 0, 0.5, 0) })\ntween:Play()',
        security="None",
    ),
    # UserInputService
    RobloxAPIDoc(
        class_name="UserInputService",
        member_type="Event",
        member_name="InputBegan",
        signature='InputBegan:Connect(function(input: InputObject, gameProcessed: boolean) ... end)',
        description="Fires when a key, mouse button, or touch screen input begins. Check gameProcessed to ignore UI typing.",
        example='UserInputService.InputBegan:Connect(function(input, gameProcessed)\n    if gameProcessed then return end\n    if input.KeyCode == Enum.KeyCode.E then\n        interact()\n    end\nend)',
        security="ClientOnly",
    ),
    # CollectionService
    RobloxAPIDoc(
        class_name="CollectionService",
        member_type="Method",
        member_name="GetTagged",
        signature='GetTagged(tag: string): {Instance}',
        description="Returns an array of all instances in the game marked with the specified CollectionService tag.",
        example='for _, spawner in CollectionService:GetTagged("MobSpawner") do\n    initSpawner(spawner)\nend',
        security="None",
    ),
    # Debris
    RobloxAPIDoc(
        class_name="Debris",
        member_type="Method",
        member_name="AddItem",
        signature='AddItem(item: Instance, lifetime: number)',
        description="Schedules an instance to be destroyed after lifetime seconds without blocking the thread.",
        example='Debris:AddItem(bulletPart, 3.0)',
        security="None",
    ),
]


class RobloxAPICatalog:
    """Search and lookup index for Roblox engine APIs to assist small LLMs."""

    def search(self, query: str, class_name: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        tokens = [t.lower() for t in query.strip().split()]
        matches: list[RobloxAPIDoc] = []

        for doc in ROBLOX_API_DOCS:
            if class_name and doc.class_name.lower() != class_name.lower():
                continue

            text_to_search = f"{doc.class_name} {doc.member_name} {doc.description} {doc.signature}".lower()
            if any(t in text_to_search for t in tokens):
                matches.append(doc)

        return [
            {
                "class_name": d.class_name,
                "member_name": d.member_name,
                "member_type": d.member_type,
                "signature": d.signature,
                "description": d.description,
                "example": d.example,
                "security": d.security,
            }
            for d in matches[:limit]
        ]
