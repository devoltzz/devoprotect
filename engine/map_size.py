# The largest map each classic Warcraft III game sends to other players, and the warning for a map above it.
import struct


MIB = 1024 * 1024
STEPS = (((1, 24, 1), 8 * MIB), ((1, 27, 2), 128 * MIB))
OLD, NEW = STEPS[0][1], STEPS[-1][1]
W3I_REFORGED = 28


def _mb(n):
    return n / float(MIB)


def classic_warning(size, original=None, w3i=None):
    if w3i is not None and (len(w3i) < 4 or struct.unpack_from('<i', w3i, 0)[0] >= W3I_REFORGED):
        return None
    if not size or size <= OLD:
        return None
    if size > NEW:
        text = ('The map is %.1f MB: the classic game sends and accepts maps up to 128 MB in a game with other players '
                '(8 MB on 1.24 to 1.27a). It still plays in single player and in a game with only computers.'
                % _mb(size))
        limit = NEW
    else:
        text = ('The map is %.1f MB: Warcraft III 1.24 to 1.27a sends and accepts maps up to 8 MB in a game with other '
                'players (1.27b and later, up to 128 MB). It still plays in single player and in a game with only '
                'computers.' % _mb(size))
        limit = OLD
    if original and original <= limit:
        text += ' The original map is %.1f MB.' % _mb(original)
    return text
