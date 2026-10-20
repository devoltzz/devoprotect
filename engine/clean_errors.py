# Removes the compiler error messages that vJass and Wurst leave in the map script.
import re


JASSHELPER = (
    re.compile(r'Attempt to destroy a null struct of type: .+'),
    re.compile(r'Double free of type: .+'),
    re.compile(r'Unable to allocate id for an object of type: .+'),
    re.compile(
        r'Warning: Unable to use allocate\(\)  when trying to create a .+ object using the interface create method\.'
    ),
    re.compile(
        r'Warning: Forced to use allocate\(\) over \.create\(\) when trying to create a .+ object using the interface create method\.'
    ),
    re.compile(r'Warning: overloaded compare operator used between structs of different types\.'),
)
WURST = (
    re.compile(r'when calling .+ in [^,]+?, line \d+'),
    re.compile(r'via function reference .+?, line \d+'),
    re.compile(r'Nullpointer exception when calling .+'),
    re.compile(r'Called .+ on invalid object\.'),
    re.compile(r'Out of memory: Could not create .+\.'),
    re.compile(r'Could not initialize package .+\.'),
)
RX_JH_CALL = re.compile(
    rb'(?:(?<=\n)|(?<=\r)|^)[ \t]*call[ \t]+DisplayTimedTextToPlayer\([ \t]*GetLocalPlayer\(\)[ \t]*,[ \t]*0[ \t]*,[ \t]*0[ \t]*,[ \t]*'
    rb'1000\.[ \t]*,[ \t]*"((?:[^"\\\r\n]|\\.)*)"[^\r\n]*\)[ \t]*(?://[^\r\n]*)?\r?\n?')
RX_JH_CALL_ANY = re.compile(
    rb'(?:(?<=\n)|(?<=\r)|^)[ \t]*call[ \t]+DisplayTimedTextToPlayer\([ \t]*GetLocalPlayer\(\)[ \t]*,[ \t]*0[ \t]*,[ \t]*0[ \t]*,[ \t]*'
    rb'1000\.[ \t]*,[^\r\n]*\)[ \t]*(?://[^\r\n]*)?\r?\n?'
)
JH_MARK = (b'Attempt to destroy a null struct of type:', b'Double free of type:',
           b'Unable to allocate id for an object of type:', b'Warning: Unable to use allocate()',
           b'Warning: Forced to use allocate() over .create()',
           b'Warning: overloaded compare operator used between structs of different types.',
           b'"Warning: "+I2S(')
RX_JASS = re.compile(rb'"((?:[^"\\\r\n]|\\.)*)"')
RX_LUA = re.compile(rb'"((?:[^"\\\r\n]|\\.)*)"|\'((?:[^\'\\\r\n]|\\.)*)\'|\[(=*)\[(.*?)\]\3\]', re.S)


def _text(b):
    try:
        s = b.decode('utf-8', 'surrogateescape')
    except Exception:
        return None
    return s


def _matches(s):
    for rx in JASSHELPER:
        if rx.fullmatch(s):
            return 'jasshelper', rx
    for rx in WURST:
        if rx.fullmatch(s):
            return 'wurst', rx
    return None, None


def _is_jass(script):
    return b'function main' in script or b'endfunction' in script


def _clean_jass(script, details):
    def _remove_quietly(m):
        body_text = _text(m.group(1))
        if body_text is not None and _matches(body_text)[0] == 'jasshelper':
            details['removed'] += 1
            return b''
        return m.group(0)
    script = RX_JH_CALL.sub(_remove_quietly, script)
    def _erase_any(m):
        ln = m.group(0)
        if b'"Warning: "+I2S(' in ln or b'"Warning: " + I2S(' in ln or \
                b'"Warning: "+I2S (' in ln or b'"Warning: " + I2S (' in ln:
            details['removed'] += 1
            return b''
        return ln
    script = RX_JH_CALL_ANY.sub(_erase_any, script)
    def _literal_text(m):
        body_text = _text(m.group(1))
        if body_text is not None:
            cluster, _rx = _matches(body_text)
            if cluster:
                details['deleted_slots'] += 1
                details['by_kind'][cluster] = details['by_kind'].get(cluster, 0) + 1
                return b'""'
        return m.group(0)
    return RX_JASS.sub(_literal_text, script)


def _clean_lua(script, details):
    def _literal_text(m):
        if m.group(1) is not None:
            raw_bytes, to_delete = m.group(1), b'""'
        elif m.group(2) is not None:
            raw_bytes, to_delete = m.group(2), b'""'
        else:
            raw_bytes, to_delete = m.group(4), b'""'
        body_text = _text(raw_bytes)
        if body_text is not None:
            cluster, _rx = _matches(body_text)
            if cluster:
                details['deleted_slots'] += 1
                details['by_kind'][cluster] = details['by_kind'].get(cluster, 0) + 1
                return to_delete
        return m.group(0)
    return RX_LUA.sub(_literal_text, script)


def _left(script, lang):
    leftovers = []
    if lang == 'jass':
        for m in RX_JASS.finditer(script):
            body_text = _text(m.group(1))
            if body_text is not None and _matches(body_text)[0]:
                leftovers.append(body_text[:80])
    else:
        for m in RX_LUA.finditer(script):
            raw_bytes = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(4))
            body_text = _text(raw_bytes or b'')
            if body_text is not None and _matches(body_text)[0]:
                leftovers.append(body_text[:80])
    for ln in script.splitlines():
        if b'DisplayTimedTextToPlayer' not in ln:
            continue
        for mark in JH_MARK:
            if mark in ln:
                leftovers.append(mark.decode('latin-1'))
    return leftovers


def clean(script, lang=None, log=None):
    log = log or (lambda *a: None)
    lang = lang or ('jass' if _is_jass(script) else 'lua')
    details = {'ok': False, 'lang': lang, 'before': len(script), 'after_diag': 0, 'removed': 0, 'deleted_slots': 0,
               'by_kind': {}, 'gate': ''}
    new = _clean_jass(script, details) if lang == 'jass' else _clean_lua(script, details)
    details['after_diag'] = len(new)
    leftovers = _left(new, lang)
    details['gate'] = (
        'ok (%d JassHelper call(s), %d literal(s): %s)'
        % (
            details['removed'],
            details['deleted_slots'],
            ', '.join('%s %d' % kv for kv in sorted(details['by_kind'].items())) or 'none',
        )
        if not leftovers
        else 'FAILED: left %r' % leftovers[:5]
    )
    details['output'] = new
    details['ok'] = not leftovers
    log('[errors] %s: %d -> %d B; %s' % (lang, details['before'], details['after_diag'], details['gate']))
    return details
