// The detector of the game's cheat codes the anti-cheat injects into a map script.
constant integer KK_TR_N=22
string array KK_tr_codigo
boolean KK_trapaca_usada=false
trigger KK_tr_gatilho=null

function KK_trapaca_contem takes string s, string sub returns boolean
    local integer n=StringLength(sub)
    local integer i=0
    local integer fim=StringLength(s)-n
    loop
        exitwhen i>fim
        if SubString(s, i, i+n)==sub then
            return true
        endif
        set i=i+1
    endloop
    return false
endfunction

function KK_trapaca_chat takes nothing returns nothing
    local string s=StringCase(GetEventPlayerChatString(), false)
    local integer i=0
    loop
        exitwhen i>=KK_TR_N
        if KK_trapaca_contem(s, KK_tr_codigo[i]) then
            if not KK_trapaca_usada then
                set KK_trapaca_usada=true
                call DisplayTimedTextToPlayer(GetTriggerPlayer(), 0, 0, 30, "|cffff3232Cheat code detected:|r saving is disabled for the rest of this game.")
            endif
            return
        endif
        set i=i+1
    endloop
endfunction

function KK_trapaca_arma takes nothing returns nothing
    local integer i=0
    if KK_tr_gatilho!=null then
        return
    endif
    set KK_tr_codigo[0]="whosyourdaddy"
    set KK_tr_codigo[1]="iseedeadpeople"
    set KK_tr_codigo[2]="greedisgood"
    set KK_tr_codigo[3]="keysersoze"
    set KK_tr_codigo[4]="leafittome"
    set KK_tr_codigo[5]="thereisnospoon"
    set KK_tr_codigo[6]="thedudeabides"
    set KK_tr_codigo[7]="warpten"
    set KK_tr_codigo[8]="pointbreak"
    set KK_tr_codigo[9]="strengthandhonor"
    set KK_tr_codigo[10]="itvexesme"
    set KK_tr_codigo[11]="allyourbasearebelongtous"
    set KK_tr_codigo[12]="somebodysetusupthebomb"
    set KK_tr_codigo[13]="whoisjohngalt"
    set KK_tr_codigo[14]="sharpandshiny"
    set KK_tr_codigo[15]="synergy"
    set KK_tr_codigo[16]="iocainepowder"
    set KK_tr_codigo[17]="riseandshine"
    set KK_tr_codigo[18]="lightsout"
    set KK_tr_codigo[19]="daylightsavings"
    set KK_tr_codigo[20]="motherland"
    set KK_tr_codigo[21]="tenthleveltaurenchieftain"
    set KK_tr_gatilho=CreateTrigger()
    loop
        exitwhen i>=bj_MAX_PLAYERS
        call TriggerRegisterPlayerChatEvent(KK_tr_gatilho, Player(i), "", false)
        set i=i+1
    endloop
    call TriggerAddAction(KK_tr_gatilho, function KK_trapaca_chat)
endfunction

function KK_trapaca_detectada takes nothing returns boolean
    return KK_trapaca_usada or IsNoVictoryCheat() or IsNoDefeatCheat()
endfunction

function KK_trapaca_save_livre takes player p returns boolean
    if KK_trapaca_detectada() then
        call DisplayTimedTextToPlayer(p, 0, 0, 15, "|cffff3232Save disabled:|r cheat codes were used in this game.")
        return false
    endif
    return true
endfunction
