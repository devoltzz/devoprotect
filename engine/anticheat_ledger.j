// The ledger the anti-cheat injects into a map script.
globals
    boolean         DEVOAC_ATIVO    = false
    integer         DEVOAC_SALTO    = 400           // gold/lumber jump that accuses (no gather event)
    boolean         DEVOAC_SO_UM    = false         // true: the ledger only runs with one human playing
    integer         DEVOAC_NTECH    = 0             // how many researched ids the sampler watches
    integer array   DEVOAC_ouro                     // the ledger, per player id
    integer array   DEVOAC_madeira
    real    array   DEVOAC_handi
    boolean array   DEVOAC_perdoa                   // a legit engine event for this player this window
    integer         DEVOAC_nher     = 0             // the watched heroes
    unit    array   DEVOAC_her
    integer array   DEVOAC_tech                     // the watched researched ids
    hashtable       DEVOAC_ht       = null          // per-hero ledger (parent = GetHandleId) and per-tech
    group           DEVOAC_g        = null
    timer           DEVOAC_t        = null
    rect            DEVOAC_mundo    = null
    integer         DEVOAC_CODE_OURO  = 1
    integer         DEVOAC_CODE_NIVEL = 2
    integer         DEVOAC_CODE_ATRIB = 3
    integer         DEVOAC_CODE_PONTO = 4
    integer         DEVOAC_CODE_HANDI = 5
    integer         DEVOAC_CODE_TECH  = 6
endglobals

//<STUB>
function ACHOOKFN takes player culpado, integer codigo, string detalhe returns nothing
    call DisplayTimedTextToForce(GetPlayersAll(), 10.0, "|cffff3333[Anti-cheat]|r a cheat changed a protected value (" + detalhe + "). It has been undone.")
endfunction
//</STUB>

function DEVOAC_Rebase takes player p returns nothing
    local integer i = GetPlayerId(p)
    set DEVOAC_ouro[i]    = GetPlayerState(p, PLAYER_STATE_RESOURCE_GOLD)
    set DEVOAC_madeira[i] = GetPlayerState(p, PLAYER_STATE_RESOURCE_LUMBER)
    set DEVOAC_handi[i]   = GetPlayerHandicapXP(p)
endfunction

function DEVOAC_RebaseTodos takes nothing returns nothing
    local integer i = 0
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        call DEVOAC_Rebase(Player(i))
        set i = i + 1
    endloop
endfunction

function DEVOAC_RebaseHero takes unit u returns nothing
    local integer id
    if u == null then
        return
    endif
    set id = GetHandleId(u)
    call SaveInteger(DEVOAC_ht, id, 1, GetHeroLevel(u))
    call SaveInteger(DEVOAC_ht, id, 3, GetHeroStr(u, false))
    call SaveInteger(DEVOAC_ht, id, 4, GetHeroAgi(u, false))
    call SaveInteger(DEVOAC_ht, id, 5, GetHeroInt(u, false))
    call SaveInteger(DEVOAC_ht, id, 6, GetHeroSkillPoints(u))
endfunction

function DEVOAC_VistoHero takes unit u returns nothing
    local integer id
    if u == null or not IsUnitType(u, UNIT_TYPE_HERO) then
        return
    endif
    set id = GetHandleId(u)
    if LoadBoolean(DEVOAC_ht, id, 0) then
        return
    endif
    call SaveBoolean(DEVOAC_ht, id, 0, true)
    call DEVOAC_RebaseHero(u)
    set DEVOAC_her[DEVOAC_nher] = u
    set DEVOAC_nher = DEVOAC_nher + 1
endfunction

function DEVOAC_RebaseTech takes player p returns nothing
    local integer i = 0
    local integer pid = GetPlayerId(p)
    loop
        exitwhen i >= DEVOAC_NTECH
        call SaveInteger(DEVOAC_ht, DEVOAC_tech[i], pid, GetPlayerTechCount(p, DEVOAC_tech[i], true))
        set i = i + 1
    endloop
endfunction

function DEVOAC_W_SetPlayerState takes player p, playerstate s, integer v returns nothing
    call SetPlayerState(p, s, v)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_SetPlayerStateBJ takes player p, playerstate s, integer v returns nothing
    call SetPlayerStateBJ(p, s, v)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_AdjustPlayerStateBJ takes integer d, player p, playerstate s returns nothing
    call AdjustPlayerStateBJ(d, p, s)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_AdjustPlayerStateSimpleBJ takes player p, playerstate s, integer d returns nothing
    call AdjustPlayerStateSimpleBJ(p, s, d)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_SetPlayerFlagBJ takes playerstate s, boolean f, player p returns nothing
    call SetPlayerFlagBJ(s, f, p)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_MeleeStartingResources takes nothing returns nothing
    call MeleeStartingResources()
    call DEVOAC_RebaseTodos()
endfunction
function DEVOAC_W_SetPlayerHandicapXP takes player p, real h returns nothing
    call SetPlayerHandicapXP(p, h)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_SetPlayerHandicapXPBJ takes player p, real h returns nothing
    call SetPlayerHandicapXPBJ(p, h)
    call DEVOAC_Rebase(p)
endfunction
function DEVOAC_W_SetHeroLevel takes unit u, integer lv, boolean eye returns nothing
    call SetHeroLevel(u, lv, eye)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_SetHeroLevelBJ takes unit u, integer lv, boolean eye returns nothing
    call SetHeroLevelBJ(u, lv, eye)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_SetHeroXP takes unit u, integer xp, boolean eye returns nothing
    call SetHeroXP(u, xp, eye)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_AddHeroXP takes unit u, integer xp, boolean eye returns nothing
    call AddHeroXP(u, xp, eye)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_AddHeroXPSwapped takes integer xp, unit u, boolean eye returns nothing
    call AddHeroXPSwapped(xp, u, eye)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_UnitStripHeroLevel takes unit u, integer n returns boolean
    local boolean r = UnitStripHeroLevel(u, n)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
    return r
endfunction
function DEVOAC_W_SetHeroStr takes unit u, integer v, boolean perm returns nothing
    call SetHeroStr(u, v, perm)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_SetHeroAgi takes unit u, integer v, boolean perm returns nothing
    call SetHeroAgi(u, v, perm)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_SetHeroInt takes unit u, integer v, boolean perm returns nothing
    call SetHeroInt(u, v, perm)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_SetHeroStat takes unit u, integer st, integer v returns nothing
    call SetHeroStat(u, st, v)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_ModifyHeroStat takes integer st, unit u, integer method, integer v returns nothing
    call ModifyHeroStat(st, u, method, v)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
endfunction
function DEVOAC_W_UnitModifySkillPoints takes unit u, integer d returns boolean
    local boolean r = UnitModifySkillPoints(u, d)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
    return r
endfunction
function DEVOAC_W_ModifyHeroSkillPoints takes unit u, integer method, integer v returns boolean
    local boolean r = ModifyHeroSkillPoints(u, method, v)
    call DEVOAC_VistoHero(u)
    call DEVOAC_RebaseHero(u)
    return r
endfunction
function DEVOAC_W_ReplaceUnitBJ takes unit u, integer id, integer st returns unit
    local unit r = ReplaceUnitBJ(u, id, st)
    call DEVOAC_VistoHero(r)
    call DEVOAC_RebaseHero(r)
    return r
endfunction
function DEVOAC_W_SetPlayerTechResearched takes player p, integer tech, integer lv returns nothing
    call SetPlayerTechResearched(p, tech, lv)
    call DEVOAC_RebaseTech(p)
endfunction
function DEVOAC_W_AddPlayerTechResearched takes player p, integer tech, integer lv returns nothing
    call AddPlayerTechResearched(p, tech, lv)
    call DEVOAC_RebaseTech(p)
endfunction
function DEVOAC_W_SetPlayerTechResearchedSwap takes integer tech, integer lv, player p returns nothing
    call SetPlayerTechResearchedSwap(tech, lv, p)
    call DEVOAC_RebaseTech(p)
endfunction
function DEVOAC_W_BlzDecPlayerTechResearched takes player p, integer tech, integer lv returns nothing
    call BlzDecPlayerTechResearched(p, tech, lv)
    call DEVOAC_RebaseTech(p)
endfunction

function DEVOAC_OnEvento takes nothing returns nothing
    local player p = GetTriggerPlayer()
    local unit ku
    if p != null then
        set DEVOAC_perdoa[GetPlayerId(p)] = true
    endif
    set ku = GetKillingUnit()
    if ku != null then
        set DEVOAC_perdoa[GetPlayerId(GetOwningPlayer(ku))] = true
    endif
    set p = null
    set ku = null
endfunction

function DEVOAC_OnPesquisa takes nothing returns nothing
    local player p = GetTriggerPlayer()
    if p != null then
        call DEVOAC_RebaseTech(p)
    endif
    set p = null
endfunction

function DEVOAC_OnHero takes nothing returns nothing
    local unit u = GetTriggerUnit()
    if u == null then
        set u = GetManipulatingUnit()
    endif
    if u != null and IsUnitType(u, UNIT_TYPE_HERO) then
        call DEVOAC_VistoHero(u)
        call DEVOAC_RebaseHero(u)
    endif
    set u = null
endfunction

function DEVOAC_FiltraHeroi takes nothing returns boolean
    return IsUnitType(GetFilterUnit(), UNIT_TYPE_HERO)
endfunction

function DEVOAC_VarreHeroes takes nothing returns nothing
    local unit u
    call GroupEnumUnitsInRect(DEVOAC_g, DEVOAC_mundo, Filter(function DEVOAC_FiltraHeroi))
    loop
        set u = FirstOfGroup(DEVOAC_g)
        exitwhen u == null
        call GroupRemoveUnit(DEVOAC_g, u)
        call DEVOAC_VistoHero(u)
    endloop
    set u = null
endfunction

function DEVOAC_TickHeroes takes nothing returns nothing
    local integer k = 0
    local unit u
    local integer id
    local player dono
    loop
        exitwhen k >= DEVOAC_nher
        set u = DEVOAC_her[k]
        if u != null and GetUnitTypeId(u) != 0 then
            set id = GetHandleId(u)
            set dono = GetOwningPlayer(u)
            if GetHeroLevel(u) > LoadInteger(DEVOAC_ht, id, 1) then
                loop
                    exitwhen GetHeroLevel(u) <= LoadInteger(DEVOAC_ht, id, 1)
                    call UnitStripHeroLevel(u, 1)
                endloop
                call ACHOOKFN(dono, DEVOAC_CODE_NIVEL, "hero level")
                call DEVOAC_RebaseHero(u)
            endif
            if GetHeroStr(u, false) != LoadInteger(DEVOAC_ht, id, 3) then
                call SetHeroStr(u, LoadInteger(DEVOAC_ht, id, 3), true)
                call ACHOOKFN(dono, DEVOAC_CODE_ATRIB, "hero strength")
            endif
            if GetHeroAgi(u, false) != LoadInteger(DEVOAC_ht, id, 4) then
                call SetHeroAgi(u, LoadInteger(DEVOAC_ht, id, 4), true)
                call ACHOOKFN(dono, DEVOAC_CODE_ATRIB, "hero agility")
            endif
            if GetHeroInt(u, false) != LoadInteger(DEVOAC_ht, id, 5) then
                call SetHeroInt(u, LoadInteger(DEVOAC_ht, id, 5), true)
                call ACHOOKFN(dono, DEVOAC_CODE_ATRIB, "hero intelligence")
            endif
            if GetHeroSkillPoints(u) > LoadInteger(DEVOAC_ht, id, 6) then
                call UnitModifySkillPoints(u, LoadInteger(DEVOAC_ht, id, 6) - GetHeroSkillPoints(u))
                call ACHOOKFN(dono, DEVOAC_CODE_PONTO, "skill points")
                call DEVOAC_RebaseHero(u)
            endif
        endif
        set k = k + 1
    endloop
    set u = null
    set dono = null
endfunction

function DEVOAC_TickTech takes nothing returns nothing
    local integer i
    local integer pid = 0
    local player p
    local integer tem
    local integer livro
    if DEVOAC_NTECH <= 0 then
        return
    endif
    loop
        exitwhen pid >= GetBJMaxPlayerSlots()
        set p = Player(pid)
        if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
            set i = 0
            loop
                exitwhen i >= DEVOAC_NTECH
                set tem = GetPlayerTechCount(p, DEVOAC_tech[i], true)
                set livro = LoadInteger(DEVOAC_ht, DEVOAC_tech[i], pid)
                if tem > livro then
                    call SetPlayerTechResearched(p, DEVOAC_tech[i], livro)
                    call ACHOOKFN(p, DEVOAC_CODE_TECH, "research")
                endif
                set i = i + 1
            endloop
        endif
        set pid = pid + 1
    endloop
    set p = null
endfunction

function DEVOAC_Tick takes nothing returns nothing
    local integer i = 0
    local player p
    local integer g
    local integer l
    local real h
    local integer agoraT = 0
    local integer livroT = 0
    if not DEVOAC_ATIVO then
        return
    endif
    call DEVOAC_VarreHeroes()
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        set p = Player(i)
        set agoraT = agoraT + GetPlayerState(p, PLAYER_STATE_RESOURCE_GOLD) + GetPlayerState(p, PLAYER_STATE_RESOURCE_LUMBER)
        set livroT = livroT + DEVOAC_ouro[i] + DEVOAC_madeira[i]
        set i = i + 1
    endloop
    set i = 0
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        set p = Player(i)
        set g = GetPlayerState(p, PLAYER_STATE_RESOURCE_GOLD)
        set l = GetPlayerState(p, PLAYER_STATE_RESOURCE_LUMBER)
        set h = GetPlayerHandicapXP(p)
        if h != DEVOAC_handi[i] then
            call SetPlayerHandicapXP(p, DEVOAC_handi[i])
            call ACHOOKFN(p, DEVOAC_CODE_HANDI, "XP handicap")
        endif
        if DEVOAC_perdoa[i] then
            set DEVOAC_ouro[i] = g
            set DEVOAC_madeira[i] = l
            set DEVOAC_perdoa[i] = false
        else
            if (g - DEVOAC_ouro[i] > DEVOAC_SALTO or l - DEVOAC_madeira[i] > DEVOAC_SALTO) and (agoraT - livroT > DEVOAC_SALTO) then
                call SetPlayerState(p, PLAYER_STATE_RESOURCE_GOLD, DEVOAC_ouro[i])
                call SetPlayerState(p, PLAYER_STATE_RESOURCE_LUMBER, DEVOAC_madeira[i])
                if GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING then
                    call ACHOOKFN(p, DEVOAC_CODE_OURO, "gold/lumber")
                endif
            else
                set DEVOAC_ouro[i] = g
                set DEVOAC_madeira[i] = l
            endif
        endif
        set i = i + 1
    endloop
    call DEVOAC_TickHeroes()
    call DEVOAC_TickTech()
    set p = null
endfunction

function DEVOAC_RegistraEvento takes trigger tg, playerunitevent ev returns nothing
    local integer i = 0
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        call TriggerRegisterPlayerUnitEvent(tg, Player(i), ev, null)
        set i = i + 1
    endloop
endfunction

function DEVOAC_Techs takes nothing returns nothing
    //<TECHS>
endfunction

function DEVOAC_Init takes nothing returns nothing
    local integer i = 0
    local integer humanos = 0
    local trigger tg
    set DEVOAC_ht = InitHashtable()
    set DEVOAC_g = CreateGroup()
    set DEVOAC_mundo = GetWorldBounds()
    call DEVOAC_Techs()
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        if GetPlayerController(Player(i)) == MAP_CONTROL_USER and GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            set humanos = humanos + 1
        endif
        set i = i + 1
    endloop
    if DEVOAC_SO_UM and humanos > 1 then
        return
    endif
    set DEVOAC_ATIVO = true
    call DEVOAC_RebaseTodos()
    set i = 0
    loop
        exitwhen i >= GetBJMaxPlayerSlots()
        call DEVOAC_RebaseTech(Player(i))
        set i = i + 1
    endloop
    call DEVOAC_VarreHeroes()
    set tg = CreateTrigger()
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_DEATH)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_SELL_ITEM)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_PAWN_ITEM)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_SELL)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_SPELL_EFFECT)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_PICKUP_ITEM)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_ISSUED_ORDER)
    call TriggerAddAction(tg, function DEVOAC_OnEvento)
    set tg = CreateTrigger()
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_RESEARCH_FINISH)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_RESEARCH_CANCEL)
    call TriggerAddAction(tg, function DEVOAC_OnPesquisa)
    set tg = CreateTrigger()
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_HERO_LEVEL)
    call DEVOAC_RegistraEvento(tg, EVENT_PLAYER_UNIT_USE_ITEM)
    call TriggerAddAction(tg, function DEVOAC_OnHero)
    set DEVOAC_t = CreateTimer()
    call TimerStart(DEVOAC_t, 2.00, true, function DEVOAC_Tick)
    set tg = null
endfunction
