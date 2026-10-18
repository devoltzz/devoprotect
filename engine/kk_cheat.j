// The detector of the game's cheat codes the anti-cheat injects into a map script.
constant integer KK_CH_N=22
string array KK_ch_code
boolean KK_cheat_used=false
trigger KK_ch_trigger=null

function KK_cheat_contains takes string s, string sub returns boolean
    local integer n=StringLength(sub)
    local integer i=0
    local integer last=StringLength(s)-n
    loop
        exitwhen i>last
        if SubString(s, i, i+n)==sub then
            return true
        endif
        set i=i+1
    endloop
    return false
endfunction

function KK_cheat_chat takes nothing returns nothing
    local string s=StringCase(GetEventPlayerChatString(), false)
    local integer i=0
    loop
        exitwhen i>=KK_CH_N
        if KK_cheat_contains(s, KK_ch_code[i]) then
            if not KK_cheat_used then
                set KK_cheat_used=true
                call DisplayTimedTextToPlayer(GetTriggerPlayer(), 0, 0, 30, "|cffff3232Cheat code detected:|r saving is disabled for the rest of this game.")
            endif
            return
        endif
        set i=i+1
    endloop
endfunction

function KK_cheat_arm takes nothing returns nothing
    local integer i=0
    if KK_ch_trigger!=null then
        return
    endif
    set KK_ch_code[0]="whosyourdaddy"
    set KK_ch_code[1]="iseedeadpeople"
    set KK_ch_code[2]="greedisgood"
    set KK_ch_code[3]="keysersoze"
    set KK_ch_code[4]="leafittome"
    set KK_ch_code[5]="thereisnospoon"
    set KK_ch_code[6]="thedudeabides"
    set KK_ch_code[7]="warpten"
    set KK_ch_code[8]="pointbreak"
    set KK_ch_code[9]="strengthandhonor"
    set KK_ch_code[10]="itvexesme"
    set KK_ch_code[11]="allyourbasearebelongtous"
    set KK_ch_code[12]="somebodysetusupthebomb"
    set KK_ch_code[13]="whoisjohngalt"
    set KK_ch_code[14]="sharpandshiny"
    set KK_ch_code[15]="synergy"
    set KK_ch_code[16]="iocainepowder"
    set KK_ch_code[17]="riseandshine"
    set KK_ch_code[18]="lightsout"
    set KK_ch_code[19]="daylightsavings"
    set KK_ch_code[20]="motherland"
    set KK_ch_code[21]="tenthleveltaurenchieftain"
    set KK_ch_trigger=CreateTrigger()
    loop
        exitwhen i>=bj_MAX_PLAYERS
        call TriggerRegisterPlayerChatEvent(KK_ch_trigger, Player(i), "", false)
        set i=i+1
    endloop
    call TriggerAddAction(KK_ch_trigger, function KK_cheat_chat)
endfunction

function KK_cheat_detected takes nothing returns boolean
    return KK_cheat_used or IsNoVictoryCheat() or IsNoDefeatCheat()
endfunction

function KK_cheat_save_free takes player p returns boolean
    if KK_cheat_detected() then
        call DisplayTimedTextToPlayer(p, 0, 0, 15, "|cffff3232Save disabled:|r cheat codes were used in this game.")
        return false
    endif
    return true
endfunction
