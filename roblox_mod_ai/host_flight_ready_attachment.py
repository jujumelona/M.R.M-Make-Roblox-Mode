"""Host-owned ship-attachment Model interface for a verified launch consumer.

Do not activate for unrelated display/attachment services. The server debit,
saved section ownership and catalog come from the existing audited builder.
This adds the physical provider, passenger seat and welded sections only when
the preflight verified an actual builder -> launch Remote pair.
"""
from __future__ import annotations


def render_flight_ready_attachment(source: str) -> str:
    def change(old: str, new: str) -> None:
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("FLIGHT_READY_SHIP_TEMPLATE_ABI_CHANGED: " + old[:70])
        source = source.replace(old, new)

    seat = r'''local function ensurePilotSeat(player, ship, anchor)
    local seat = ship:FindFirstChild("PilotSeat")
    if seat and not seat:IsA("VehicleSeat") then return false end
    if not seat then
        seat = Instance.new("VehicleSeat")
        seat.Name = "PilotSeat"
        seat.Size = Vector3.new(3, 1, 3)
        seat.Anchored = false
        seat.Parent = ship
    end
    seat.CFrame = anchor.CFrame * CFrame.new(0, 3.2, 0)
    local weld = seat:FindFirstChild("PilotWeld")
    if weld and not weld:IsA("WeldConstraint") then return false end
    if not weld then
        weld = Instance.new("WeldConstraint")
        weld.Name = "PilotWeld"
        weld.Part0 = anchor
        weld.Part1 = seat
        weld.Parent = seat
    end
    local prompt = anchor:FindFirstChild("BoardVehicle")
    if prompt and not prompt:IsA("ProximityPrompt") then return false end
    if not prompt then
        prompt = Instance.new("ProximityPrompt")
        prompt.Name = "BoardVehicle"
        prompt.ActionText = "Board"
        prompt.ObjectText = "Assembled vehicle"
        prompt.MaxActivationDistance = 10
        prompt.RequiresLineOfSight = false
        prompt.Parent = anchor
        prompt.Triggered:Connect(function(requester)
            if requester ~= player or player.Parent ~= Players
                or ship:GetAttribute("OwnerUserId") ~= player.UserId
                or seat.Occupant ~= nil then return end
            local character = player.Character
            local humanoid = character and character:FindFirstChildOfClass("Humanoid")
            local root = character and character:FindFirstChild("HumanoidRootPart")
            if not humanoid or humanoid.Health <= 0
                or not root or not root:IsA("BasePart")
                or (root.Position - anchor.Position).Magnitude > 12
                or not Service.GetOwnedActor(player) then return end
            seat:Sit(humanoid)
        end)
    end
    return true
end
'''
    passengers = r'''-- Flight-ready models require actual passenger seats rather than
-- merely scanning descendants for seat occupants that cannot board.
local function ensurePassengerSeats(player, ship, anchor)
    for index=1,2 do
        local name="PassengerSeat"..tostring(index)
        local seat=ship:FindFirstChild(name)
        if seat and not seat:IsA("Seat") then return false end
        if not seat then
            seat=Instance.new("Seat")
            seat.Name=name
            seat.Size=Vector3.new(2.5,1,2.5)
            seat.Anchored=false
            seat.Parent=ship
        end
        -- Keep guests clear of the pilot and the positive-X built sections.
        local z=index==1 and -3 or 3
        seat.CFrame=anchor.CFrame*CFrame.new(-3,3.2,z)
        local weld=seat:FindFirstChild("PassengerWeld")
        if weld and (not weld:IsA("WeldConstraint")
            or weld.Part0~=anchor or weld.Part1~=seat) then return false end
        if not weld then
            weld=Instance.new("WeldConstraint")
            weld.Name="PassengerWeld"
            weld.Part0=anchor
            weld.Part1=seat
            weld.Parent=seat
        end
        local promptName="BoardPassenger"..tostring(index)
        local prompt=anchor:FindFirstChild(promptName)
        if prompt and not prompt:IsA("ProximityPrompt") then return false end
        if not prompt then
            prompt=Instance.new("ProximityPrompt")
            prompt.Name=promptName
            prompt.ActionText="Board passenger seat "..tostring(index)
            prompt.ObjectText="Assembled vehicle"
            prompt.MaxActivationDistance=10
            prompt.RequiresLineOfSight=false
            prompt.Parent=anchor
            prompt.Triggered:Connect(function(requester)
                if requester==player or not requester:IsA("Player")
                    or requester.Parent~=Players
                    or player.Parent~=Players
                    or ship:GetAttribute("OwnerUserId")~=player.UserId
                    or seat.Occupant~=nil
                    or Service.GetOwnedActor(player)~=ship then return end
                local character=requester.Character
                local humanoid=character and character:FindFirstChildOfClass("Humanoid")
                local root=character and character:FindFirstChild("HumanoidRootPart")
                if not humanoid or humanoid.Health<=0
                    or not root or not root:IsA("BasePart")
                    or humanoid.Sit
                    or (root.Position-anchor.Position).Magnitude>12 then return end
                seat:Sit(humanoid)
            end)
        end
    end
    return true
end
'''
    change("local function resolveShip(player)\n",
           seat + passengers + "local function resolveShip(player)\n")
    change(
        "    shipModels[player] = ship\n    return ship, anchor, parts",
        "    ship.PrimaryPart = anchor\n"
        "    shipModels[player] = ship\n"
        "    if not ensurePilotSeat(player, ship, anchor) then return nil end\n"
        "    if not ensurePassengerSeats(player, ship, anchor) then return nil end\n"
        "    return ship, anchor, parts",
    )
    change(
        '''    part.Anchored = true
    part.Size = Vector3.new(5, 2, 6)
    part.Position = anchor.Position + Vector3.new(
        definition.ordinal * 5, 4, 0)
    part:SetAttribute("RMMAssemblySection", id)
    part.Parent = parts
    return true''',
        '''    part.Anchored = false
    part.Size = Vector3.new(5, 2, 6)
    part.CFrame = anchor.CFrame * CFrame.new(definition.ordinal * 5, 4, 0)
    part:SetAttribute("RMMAssemblySection", id)
    part.Parent = parts
    local joint = Instance.new("WeldConstraint")
    joint.Name = "SectionWeld"
    joint.Part0 = anchor
    joint.Part1 = part
    joint.Parent = part
    return true''',
    )
    change("function Service.start(services)\n",
           "function Service.start(services)\n    Service._services = services\n")
    provider = r'''
-- The only launchable actor is the exact Model containing every saved part.
-- A single decorative Part, user-supplied actor or unfinished build is refused.
function Service.GetOwnedActor(player)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players then return nil end
    local services = Service._services
    if not services then return nil end
    local profile = services.PlayerDataManager.GetState(player, "RMMShipSections")
    if not profile or type(profile.sections) ~= "table" then return nil end
    local ship = shipModels[player]
    if not ship or not ship:IsA("Model") or ship.Parent == nil
        or ship:GetAttribute("OwnerUserId") ~= player.UserId then return nil end
    local anchor = ship:FindFirstChild("AssemblyAnchor")
    local seat = ship:FindFirstChild("PilotSeat")
    local sections = ship:FindFirstChild("AssembledSections")
    if not anchor or not anchor:IsA("BasePart")
        or ship.PrimaryPart ~= anchor
        or not seat or not seat:IsA("VehicleSeat")
        or not sections or not sections:IsA("Folder") then return nil end
    local pilotWeld = seat:FindFirstChild("PilotWeld")
    if not pilotWeld or not pilotWeld:IsA("WeldConstraint")
        or pilotWeld.Part0 ~= anchor or pilotWeld.Part1 ~= seat then return nil end
    for index=1,2 do
        local passenger=ship:FindFirstChild("PassengerSeat"..tostring(index))
        if not passenger or not passenger:IsA("Seat") then return nil end
        local passengerWeld=passenger:FindFirstChild("PassengerWeld")
        if not passengerWeld or not passengerWeld:IsA("WeldConstraint")
            or passengerWeld.Part0~=anchor
            or passengerWeld.Part1~=passenger then return nil end
    end
    local total = 0
    for id in pairs(SECTIONS) do
        total += 1
        local record = profile.sections[id]
        local part = sections:FindFirstChild(id)
        if type(record) ~= "table" or record.owned ~= true
            or not part or not part:IsA("BasePart") then return nil end
        local weld = part:FindFirstChild("SectionWeld")
        if not weld or not weld:IsA("WeldConstraint")
            or weld.Part0 ~= anchor or weld.Part1 ~= part then return nil end
    end
    if total == 0 then return nil end
    return ship
end
'''
    change("return Service\n", provider + "return Service\n")
    return source
