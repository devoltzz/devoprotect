# Writes the MPQ barriers: a block bitmap at the end of the file, or the archive moved to 128 MiB.
import struct



HDR = '<4sIIHHIIII'


def read_mpq_header(b):
    off = next(o for o in range(0, min(len(b), 0x10000), 0x200) if b[o:o + 4] == b'MPQ\x1a')
    field_list = struct.unpack_from(HDR, b, off)
    return off, field_list


def v6_bitmap(b, all_present=False):
    if not b:
        raise ValueError('the bitmap needs a non-empty MPQ')
    block_entry = 0x4000
    n_blocks = ((len(b) - 1) // block_entry) + 1
    n_bytes = (n_blocks + 7) // 8
    bitmap = bytearray(b'\xff' * n_bytes if all_present else b'\0' * n_bytes)
    if all_present and n_blocks & 7:
        bitmap[-1] = (1 << (n_blocks & 7)) - 1
    footer = struct.pack('<6I', 0x33767470, 3, 10958, len(b) & 0xFFFFFFFF, len(b) >> 32, block_entry)
    return bytes(b) + bytes(bitmap) + footer


def v7_header128m(b, pos=0x08000000):
    off = read_mpq_header(b)[0]
    if pos <= off or pos & 0x1FF:
        raise ValueError('the new position must be a multiple of 512 and past the current header')
    return bytes(b[:off]) + b'\0' * (pos - off) + bytes(b[off:])

