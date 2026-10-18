# Reads the names of the objects of a map (units, items, abilities) for the trigger names.
import re




_RX_STRING_B = re.compile(rb'^(?:\xef\xbb\xbf)?(?i:STRING)[ \t]+(\d+)')
_RX_STRING_S = re.compile(r'^(?:﻿)?(?i:STRING)[ \t]+(\d+)')
_RX_SKIP_B = re.compile(rb'^[ \t]*(?://[^\r\n]*)?\r?$')
_RX_SKIP_S = re.compile(r'^[ \t]*(?://[^\r\n]*)?\r?$')
_RX_OPEN_B = re.compile(rb'^[ \t]*\{')
_RX_OPEN_S = re.compile(r'^[ \t]*\{')
_RX_CLOSE_B = re.compile(rb'^\}[ \t]*\r?$')
_RX_CLOSE_S = re.compile(r'^\}[ \t]*\r?$')


class WtsEntry(object):
    __slots__ = ('_d', '_s', '_e', '_n', '_s2', '_e2')

    def __init__(self, data, start, end, number_span, body_span):
        self._d, self._s, self._e, self._n, (self._s2, self._e2) = data, start, end, number_span, body_span

    def group(self, n=0):
        if n == 1:
            return self._d[self._n[0]:self._n[1]]
        if n == 2:
            return self._d[self._s2:self._e2]
        return self._d[self._s:self._e]

    def start(self, n=0):
        return self._n[0] if n == 1 else self._s2 if n == 2 else self._s

    def end(self, n=0):
        return self._n[1] if n == 1 else self._e2 if n == 2 else self._e


def wts_entries(data):
    bts = isinstance(data, (bytes, bytearray))
    rx_string, rx_skip, rx_open, rx_close = (_RX_STRING_B, _RX_SKIP_B, _RX_OPEN_B, _RX_CLOSE_B) if bts else \
        (_RX_STRING_S, _RX_SKIP_S, _RX_OPEN_S, _RX_CLOSE_S)
    nl = b'\n' if bts else '\n'
    cr = b'\r' if bts else '\r'
    lines = data.split(nl)
    offs, off = [], 0
    for ln in lines:
        offs.append(off)
        off += len(ln) + 1
    out = []
    i, n = 0, len(lines)
    while i < n:
        m = rx_string.match(lines[i])
        if not m:
            i += 1
            continue
        start, number = offs[i], (offs[i] + m.start(1), offs[i] + m.end(1))
        j = i + 1
        while j < n and rx_skip.match(lines[j]):
            j += 1
        if j >= n or not rx_open.match(lines[j]):
            i += 1
            continue
        body_start = offs[j] + len(lines[j]) + 1
        k = j + 1
        while k < n and not rx_close.match(lines[k]):
            k += 1
        if k >= n:
            break
        body_end = max(body_start, offs[k] - 1)
        if body_end > body_start and data[body_end - 1:body_end] == cr:
            body_end -= 1
        out.append(WtsEntry(data, start, offs[k] + len(lines[k]), number, (body_start, body_end)))
        i = k + 1
    return out

