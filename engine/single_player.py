# Finds and removes the lock that ends the game when a map is played alone.

import name_recovery
import object_names


JASS_FILES = ('war3map.j', 'scripts\\war3map.j')
LUA_FILE = 'war3map.lua'
ENDS = {'EndGame': 'ends the game', 'EndGameBJ': 'ends the game', 'CustomVictoryBJ': 'ends the game',
        'CustomDefeatBJ': 'defeats the players', 'CustomDefeatDialogBJ': 'defeats the players',
        'MeleeDoDefeat': 'defeats the players', 'RemovePlayer': 'removes the players',
        'RemovePlayerPreserveUnitsBJ': 'removes the players', 'RestartGame': 'restarts the game',
        'CustomRestartBJ': 'restarts the game'}
CRASH, FREEZE = 'crashes the game', 'freezes the game'
NO_SAVE, SAVE_FLAG = 'disables saving', 'breaks the save code'
CHEAT_GUARD = 'turns on a cheat detection that defeats the players'
PUNISH = frozenset(ENDS.values()) | frozenset((CRASH, FREEZE, NO_SAVE, SAVE_FLAG, CHEAT_GUARD))
def script_of(a):
    j_name = j = None
    for n in JASS_FILES:
        b = name_recovery._read(a, n)
        if b is not None:
            j_name, j = n, b
            break
    lang = name_recovery.language_from_w3i(name_recovery._read(a, 'war3map.w3i'))
    out = {'language': None, 'file': None, 'bytes': None, 'copies': [], 'compiled': False}
    if a.find(LUA_FILE) and (lang == 1 or j is None):
        out.update({'language': 'lua', 'file': LUA_FILE, 'bytes': name_recovery._read(a, LUA_FILE)})
    elif j is not None:
        compiled = (len(j) < 450 and bool(a.find('kkmap.jc'))) or name_recovery.script_j2b(a, j)
        copies = [n for n in JASS_FILES if n != j_name and a.find(n) and name_recovery._read(a, n) == j]
        out.update({'language': 'jass', 'file': j_name, 'bytes': j, 'copies': copies, 'compiled': bool(compiled)})
    return out


def read_map(path):
    a = name_recovery._open(path)
    sc = script_of(a)
    strings = object_names.strings(name_recovery._read(a, 'war3map.wts'))
    return a, sc, strings

