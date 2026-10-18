-- The ledger the anti-cheat injects into a map script.
;(function()
    local JUMP = 400
    local ONLY_ONE = false
    local MAXP = (GetBJMaxPlayerSlots and GetBJMaxPlayerSlots()) or 28
    local techs = {}
    --[[TECHS]]

    local _SetPlayerState       = SetPlayerState
    local _SetHeroLevel         = SetHeroLevel
    local _SetHeroXP            = SetHeroXP
    local _AddHeroXP            = AddHeroXP
    local _UnitStripHeroLevel   = UnitStripHeroLevel
    local _SetHeroStr           = SetHeroStr
    local _SetHeroAgi           = SetHeroAgi
    local _SetHeroInt           = SetHeroInt
    local _UnitModifySkillPoints= UnitModifySkillPoints
    local _SetPlayerHandicapXP  = SetPlayerHandicapXP
    local _SetPlayerTechResearched    = SetPlayerTechResearched
    local _AddPlayerTechResearched    = AddPlayerTechResearched
    local _BlzDecPlayerTechResearched = BlzDecPlayerTechResearched

    local GPS, SPS = GetPlayerState, _SetPlayerState
    local GOLD, LUMBER = PLAYER_STATE_RESOURCE_GOLD, PLAYER_STATE_RESOURCE_LUMBER

    local gold, lumber, handi, forgive = {}, {}, {}, {}
    local heroes, hled, tled = {}, {}, {}
    local active = false

    local function pid(p) return GetPlayerId(p) end

    local function rebase(p)
        local i = pid(p)
        gold[i]    = GPS(p, GOLD)
        lumber[i] = GPS(p, LUMBER)
        handi[i]   = GetPlayerHandicapXP(p)
    end

    local function rebaseAll()
        for i = 0, MAXP - 1 do rebase(Player(i)) end
    end

    local function rebaseHero(u)
        if not u then return end
        local id = GetHandleId(u)
        local e = hled[id]
        if not e then e = {}; hled[id] = e end
        e.lvl   = GetHeroLevel(u)
        e.str   = GetHeroStr(u, false)
        e.agi   = GetHeroAgi(u, false)
        e.int   = GetHeroInt(u, false)
        e.skill = GetHeroSkillPoints(u)
    end

    local function seenHero(u)
        if not u or not IsUnitType(u, UNIT_TYPE_HERO) then return end
        local id = GetHandleId(u)
        local e = hled[id]
        if e and e.seen then return end
        if not e then e = {}; hled[id] = e end
        e.seen = true
        rebaseHero(u)
        heroes[#heroes + 1] = u
    end

    local function rebaseTech(p)
        local i = pid(p)
        for _, t in ipairs(techs) do
            tled[t] = tled[t] or {}
            tled[t][i] = GetPlayerTechCount(p, t, true)
        end
    end

    function SetPlayerState(p, s, v) _SetPlayerState(p, s, v); rebase(p) end
    function SetHeroLevel(u, lv, e) _SetHeroLevel(u, lv, e); seenHero(u); rebaseHero(u) end
    function SetHeroXP(u, xp, e) _SetHeroXP(u, xp, e); seenHero(u); rebaseHero(u) end
    function AddHeroXP(u, xp, e) _AddHeroXP(u, xp, e); seenHero(u); rebaseHero(u) end
    function UnitStripHeroLevel(u, n) local r = _UnitStripHeroLevel(u, n); seenHero(u); rebaseHero(u); return r end
    function SetHeroStr(u, v, perm) _SetHeroStr(u, v, perm); seenHero(u); rebaseHero(u) end
    function SetHeroAgi(u, v, perm) _SetHeroAgi(u, v, perm); seenHero(u); rebaseHero(u) end
    function SetHeroInt(u, v, perm) _SetHeroInt(u, v, perm); seenHero(u); rebaseHero(u) end
    function UnitModifySkillPoints(u, d) local r = _UnitModifySkillPoints(u, d); seenHero(u); rebaseHero(u); return r end
    function SetPlayerHandicapXP(p, h) _SetPlayerHandicapXP(p, h); rebase(p) end
    function SetPlayerTechResearched(p, t, lv) _SetPlayerTechResearched(p, t, lv); rebaseTech(p) end
    function AddPlayerTechResearched(p, t, lv) _AddPlayerTechResearched(p, t, lv); rebaseTech(p) end
    if _BlzDecPlayerTechResearched then
        function BlzDecPlayerTechResearched(p, t, lv) _BlzDecPlayerTechResearched(p, t, lv); rebaseTech(p) end
    end

    local function onEvent()
        local p = GetTriggerPlayer()
        if p then forgive[pid(p)] = true end
        local ku = GetKillingUnit()
        if ku then forgive[pid(GetOwningPlayer(ku))] = true end
    end
    local function onResearch()
        local p = GetTriggerPlayer()
        if p then rebaseTech(p) end
    end
    local function onHero()
        local u = GetTriggerUnit() or GetManipulatingUnit()
        if u and IsUnitType(u, UNIT_TYPE_HERO) then seenHero(u); rebaseHero(u) end
    end

    local function scanHeroes()
        local g = CreateGroup()
        GroupEnumUnitsInRect(g, GetWorldBounds(), Filter(function() return IsUnitType(GetFilterUnit(), UNIT_TYPE_HERO) end))
        while true do
            local u = FirstOfGroup(g)
            if not u then break end
            GroupRemoveUnit(g, u)
            seenHero(u)
        end
        DestroyGroup(g)
    end

    local function tickHeroes()
        for _, u in ipairs(heroes) do
            if u and GetUnitTypeId(u) ~= 0 then
                local id = GetHandleId(u)
                local e = hled[id]
                local owner = GetOwningPlayer(u)
                if e then
                    if GetHeroLevel(u) > e.lvl then
                        while GetHeroLevel(u) > e.lvl do _UnitStripHeroLevel(u, 1) end
                        ACHOOKFN(owner, 2, "hero level")
                        rebaseHero(u)
                    end
                    if GetHeroStr(u, false) ~= e.str then _SetHeroStr(u, e.str, true); ACHOOKFN(owner, 3, "hero strength") end
                    if GetHeroAgi(u, false) ~= e.agi then _SetHeroAgi(u, e.agi, true); ACHOOKFN(owner, 3, "hero agility") end
                    if GetHeroInt(u, false) ~= e.int then _SetHeroInt(u, e.int, true); ACHOOKFN(owner, 3, "hero intelligence") end
                    if GetHeroSkillPoints(u) > e.skill then
                        _UnitModifySkillPoints(u, e.skill - GetHeroSkillPoints(u))
                        ACHOOKFN(owner, 4, "skill points")
                        rebaseHero(u)
                    end
                end
            end
        end
    end

    local function tickTech()
        if #techs == 0 then return end
        for i = 0, MAXP - 1 do
            local p = Player(i)
            if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                for _, t in ipairs(techs) do
                    local booked = (tled[t] and tled[t][i]) or 0
                    if GetPlayerTechCount(p, t, true) > booked then
                        _SetPlayerTechResearched(p, t, booked)
                        ACHOOKFN(p, 6, "research")
                    end
                end
            end
        end
    end

    local function tick()
        if not active then return end
        scanHeroes()
        local nowT, bookedT = 0, 0
        for i = 0, MAXP - 1 do
            local p = Player(i)
            nowT = nowT + GPS(p, GOLD) + GPS(p, LUMBER)
            bookedT = bookedT + (gold[i] or 0) + (lumber[i] or 0)
        end
        for i = 0, MAXP - 1 do
            local p = Player(i)
            local g = GPS(p, GOLD)
            local l = GPS(p, LUMBER)
            local h = GetPlayerHandicapXP(p)
            if h ~= handi[i] then _SetPlayerHandicapXP(p, handi[i]); ACHOOKFN(p, 5, "XP handicap") end
            if forgive[i] then
                gold[i] = g; lumber[i] = l; forgive[i] = false
            elseif (g - (gold[i] or 0) > JUMP or l - (lumber[i] or 0) > JUMP) and (nowT - bookedT > JUMP) then
                SPS(p, GOLD, gold[i] or 0)
                SPS(p, LUMBER, lumber[i] or 0)
                if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                    ACHOOKFN(p, 1, "gold/lumber")
                end
            else
                gold[i] = g; lumber[i] = l
            end
        end
        tickHeroes()
        tickTech()
    end

    local function init()
        local humans = 0
        for i = 0, MAXP - 1 do
            local p = Player(i)
            if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                humans = humans + 1
            end
        end
        if ONLY_ONE and humans > 1 then return end
        active = true
        rebaseAll()
        for i = 0, MAXP - 1 do rebaseTech(Player(i)) end
        scanHeroes()
        local tg = CreateTrigger()
        for i = 0, MAXP - 1 do
            local p = Player(i)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_DEATH, nil)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_SELL_ITEM, nil)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_PAWN_ITEM, nil)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_SELL, nil)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_SPELL_EFFECT, nil)
            TriggerRegisterPlayerUnitEvent(tg, p, EVENT_PLAYER_UNIT_PICKUP_ITEM, nil)
        end
        TriggerAddAction(tg, onEvent)
        local tp = CreateTrigger()
        for i = 0, MAXP - 1 do
            local p = Player(i)
            TriggerRegisterPlayerUnitEvent(tp, p, EVENT_PLAYER_UNIT_RESEARCH_FINISH, nil)
            TriggerRegisterPlayerUnitEvent(tp, p, EVENT_PLAYER_UNIT_RESEARCH_CANCEL, nil)
        end
        TriggerAddAction(tp, onResearch)
        local th = CreateTrigger()
        for i = 0, MAXP - 1 do
            local p = Player(i)
            TriggerRegisterPlayerUnitEvent(th, p, EVENT_PLAYER_HERO_LEVEL, nil)
            TriggerRegisterPlayerUnitEvent(th, p, EVENT_PLAYER_UNIT_USE_ITEM, nil)
        end
        TriggerAddAction(th, onHero)
        local t = CreateTimer()
        TimerStart(t, 2.0, true, tick)
    end

    --<STUB>
    function ACHOOKFN(culprit, ckind, cdetail)
        DisplayTimedTextToForce(GetPlayersAll(), 10.0, "|cffff3333[Anti-cheat]|r a cheat changed a protected value (" .. cdetail .. "). It has been undone.")
    end
    --</STUB>

    _G.DevoAC_Ledger_Init = init
    local t0 = CreateTimer()
    TimerStart(t0, 0.0, false, init)
end)()
