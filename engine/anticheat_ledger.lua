-- The ledger the anti-cheat injects into a map script.
;(function()
    local SALTO = 400
    local SO_UM = false
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

    local ouro, madeira, handi, perdoa = {}, {}, {}, {}
    local heroes, hled, tled = {}, {}, {}
    local ativo = false

    local function pid(p) return GetPlayerId(p) end

    local function rebase(p)
        local i = pid(p)
        ouro[i]    = GPS(p, GOLD)
        madeira[i] = GPS(p, LUMBER)
        handi[i]   = GetPlayerHandicapXP(p)
    end

    local function rebaseTodos()
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

    local function vistoHero(u)
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
    function SetHeroLevel(u, lv, e) _SetHeroLevel(u, lv, e); vistoHero(u); rebaseHero(u) end
    function SetHeroXP(u, xp, e) _SetHeroXP(u, xp, e); vistoHero(u); rebaseHero(u) end
    function AddHeroXP(u, xp, e) _AddHeroXP(u, xp, e); vistoHero(u); rebaseHero(u) end
    function UnitStripHeroLevel(u, n) local r = _UnitStripHeroLevel(u, n); vistoHero(u); rebaseHero(u); return r end
    function SetHeroStr(u, v, perm) _SetHeroStr(u, v, perm); vistoHero(u); rebaseHero(u) end
    function SetHeroAgi(u, v, perm) _SetHeroAgi(u, v, perm); vistoHero(u); rebaseHero(u) end
    function SetHeroInt(u, v, perm) _SetHeroInt(u, v, perm); vistoHero(u); rebaseHero(u) end
    function UnitModifySkillPoints(u, d) local r = _UnitModifySkillPoints(u, d); vistoHero(u); rebaseHero(u); return r end
    function SetPlayerHandicapXP(p, h) _SetPlayerHandicapXP(p, h); rebase(p) end
    function SetPlayerTechResearched(p, t, lv) _SetPlayerTechResearched(p, t, lv); rebaseTech(p) end
    function AddPlayerTechResearched(p, t, lv) _AddPlayerTechResearched(p, t, lv); rebaseTech(p) end
    if _BlzDecPlayerTechResearched then
        function BlzDecPlayerTechResearched(p, t, lv) _BlzDecPlayerTechResearched(p, t, lv); rebaseTech(p) end
    end

    local function onEvento()
        local p = GetTriggerPlayer()
        if p then perdoa[pid(p)] = true end
        local ku = GetKillingUnit()
        if ku then perdoa[pid(GetOwningPlayer(ku))] = true end
    end
    local function onPesquisa()
        local p = GetTriggerPlayer()
        if p then rebaseTech(p) end
    end
    local function onHero()
        local u = GetTriggerUnit() or GetManipulatingUnit()
        if u and IsUnitType(u, UNIT_TYPE_HERO) then vistoHero(u); rebaseHero(u) end
    end

    local function varreHeroes()
        local g = CreateGroup()
        GroupEnumUnitsInRect(g, GetWorldBounds(), Filter(function() return IsUnitType(GetFilterUnit(), UNIT_TYPE_HERO) end))
        while true do
            local u = FirstOfGroup(g)
            if not u then break end
            GroupRemoveUnit(g, u)
            vistoHero(u)
        end
        DestroyGroup(g)
    end

    local function tickHeroes()
        for _, u in ipairs(heroes) do
            if u and GetUnitTypeId(u) ~= 0 then
                local id = GetHandleId(u)
                local e = hled[id]
                local dono = GetOwningPlayer(u)
                if e then
                    if GetHeroLevel(u) > e.lvl then
                        while GetHeroLevel(u) > e.lvl do _UnitStripHeroLevel(u, 1) end
                        ACHOOKFN(dono, 2, "hero level")
                        rebaseHero(u)
                    end
                    if GetHeroStr(u, false) ~= e.str then _SetHeroStr(u, e.str, true); ACHOOKFN(dono, 3, "hero strength") end
                    if GetHeroAgi(u, false) ~= e.agi then _SetHeroAgi(u, e.agi, true); ACHOOKFN(dono, 3, "hero agility") end
                    if GetHeroInt(u, false) ~= e.int then _SetHeroInt(u, e.int, true); ACHOOKFN(dono, 3, "hero intelligence") end
                    if GetHeroSkillPoints(u) > e.skill then
                        _UnitModifySkillPoints(u, e.skill - GetHeroSkillPoints(u))
                        ACHOOKFN(dono, 4, "skill points")
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
                    local livro = (tled[t] and tled[t][i]) or 0
                    if GetPlayerTechCount(p, t, true) > livro then
                        _SetPlayerTechResearched(p, t, livro)
                        ACHOOKFN(p, 6, "research")
                    end
                end
            end
        end
    end

    local function tick()
        if not ativo then return end
        varreHeroes()
        local agoraT, livroT = 0, 0
        for i = 0, MAXP - 1 do
            local p = Player(i)
            agoraT = agoraT + GPS(p, GOLD) + GPS(p, LUMBER)
            livroT = livroT + (ouro[i] or 0) + (madeira[i] or 0)
        end
        for i = 0, MAXP - 1 do
            local p = Player(i)
            local g = GPS(p, GOLD)
            local l = GPS(p, LUMBER)
            local h = GetPlayerHandicapXP(p)
            if h ~= handi[i] then _SetPlayerHandicapXP(p, handi[i]); ACHOOKFN(p, 5, "XP handicap") end
            if perdoa[i] then
                ouro[i] = g; madeira[i] = l; perdoa[i] = false
            elseif (g - (ouro[i] or 0) > SALTO or l - (madeira[i] or 0) > SALTO) and (agoraT - livroT > SALTO) then
                SPS(p, GOLD, ouro[i] or 0)
                SPS(p, LUMBER, madeira[i] or 0)
                if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                    ACHOOKFN(p, 1, "gold/lumber")
                end
            else
                ouro[i] = g; madeira[i] = l
            end
        end
        tickHeroes()
        tickTech()
    end

    local function init()
        local humanos = 0
        for i = 0, MAXP - 1 do
            local p = Player(i)
            if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                humanos = humanos + 1
            end
        end
        if SO_UM and humanos > 1 then return end
        ativo = true
        rebaseTodos()
        for i = 0, MAXP - 1 do rebaseTech(Player(i)) end
        varreHeroes()
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
        TriggerAddAction(tg, onEvento)
        local tp = CreateTrigger()
        for i = 0, MAXP - 1 do
            local p = Player(i)
            TriggerRegisterPlayerUnitEvent(tp, p, EVENT_PLAYER_UNIT_RESEARCH_FINISH, nil)
            TriggerRegisterPlayerUnitEvent(tp, p, EVENT_PLAYER_UNIT_RESEARCH_CANCEL, nil)
        end
        TriggerAddAction(tp, onPesquisa)
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
    function ACHOOKFN(culpado, codigo, detalhe)
        DisplayTimedTextToForce(GetPlayersAll(), 10.0, "|cffff3333[Anti-cheat]|r a cheat changed a protected value (" .. detalhe .. "). It has been undone.")
    end
    --</STUB>

    _G.DevoAC_Caixa_Init = init
    local t0 = CreateTimer()
    TimerStart(t0, 0.0, false, init)
end)()
