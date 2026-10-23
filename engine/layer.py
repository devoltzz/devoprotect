# Assembles the port layer: the JASS parts that give the platform natives a body on Warcraft III 3.0.
import os
import re


HERE = os.path.dirname(os.path.abspath(__file__))
KK_COMPAT = os.environ.get('KK_COMPAT_DIR') or os.path.join(HERE, 'compat')
KW_JASS = set("""if and or not return function then else elseif endif loop endloop exitwhen set call
local globals endglobals takes returns nothing array constant native type extends debug in null true
false endfunction""".split())

RX_GLOBAL = re.compile(
    r'^\s*(constant\s+)?(integer|real|boolean|string|handle|code|hashtable|timer|trigger|group|'
    r'force|region|rect|unit|item|player|effect|ability|destructable|dialog|button|lightning|widget|location|'
    r'image|texttag|ubersplat|sound|quest|questitem|defeatcondition|timerdialog|leaderboard|'
    r'multiboard|multiboarditem|trackable|framehandle|originframetype|framepointtype|'
    r'frameeventtype|textaligntype|oskeytype|eventid|eventtype|playerevent|playerunitevent|'
    r'unitevent|widgetevent|dialogevent|unitstate|abilityreallevelfield|abilityintegerlevelfield|'
    r'abilitystringlevelfield|abilitybooleanlevelfield|unitrealfield|unitintegerfield|'
    r'unitstringfield|unitbooleanfield|itemrealfield|itemintegerfield|itemstringfield|'
    r'limitop)\s+(array\s+)?[A-Za-z_]\w*\s*(=[^\r\n]*)?$')


def split_globals(block_entry):
    globals_block = []
    rest = []
    for lx in block_entry.split('\n'):
        s = lx.strip()
        if s.startswith('native ') or s.startswith('constant native '):
            rest.append(lx)
            continue
        if RX_GLOBAL.match(lx):
            globals_block.append(s)
        else:
            rest.append(lx)
    return globals_block, '\n'.join(rest)

