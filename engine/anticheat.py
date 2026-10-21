# The in-game anti-cheat as one step: the hook, the ledger, the cheat codes, decoy names, in order.

PARTS = ('ledger', 'codes', 'decoys', 'bj', 'globals')
STANDARD = ('ledger', 'codes', 'decoys', 'bj')
ORDER = {'jass': ('codes', 'ledger', 'decoys', 'bj', 'globals'), 'lua': ('ledger', 'codes', 'globals', 'bj', 'decoys')}
CODES_MODES = ('auto', 'humans', 'reload', 'humans+reload')


def _part(fname, body_text, language, hook, options, ref=None):
    if fname == 'codes':
        import anticheat_codes
        import anticheat_policy
        return anticheat_codes.inject(body_text, language, hook=hook, stub=False, method=options['codes_mode'],
                                      type_name=anticheat_policy.CODE_KIND, ref=ref)
    if fname == 'ledger':
        import anticheat_ledger
        return anticheat_ledger.inject(body_text, language, hook_name=hook, stub=False, gold_jump=options['gold_jump'])
    if fname == 'decoys':
        import decoy_names
        return decoy_names.inject(body_text, language, per_pack=options['per_pack'])
    if fname == 'bj':
        import anticheat_bj_lua
        return anticheat_bj_lua.inject(body_text, language, hook=hook, stub=False, ref=ref)
    if fname == 'globals':
        import anticheat_globals_lua
        return anticheat_globals_lua.inject(body_text, language, hook=hook, stub=False, ref=ref)
    raise ValueError('piece %r: not one of %s' % (fname, ', '.join(PARTS)))


def _effect(fname, details):
    if fname == 'decoys':
        return bool(details.get('applied')), details.get('why')
    if fname in ('bj', 'globals'):
        return bool(details.get('changed')), details.get('why')
    if fname == 'codes' and details.get('already_injected'):
        return False, 'already injected'
    return True, None


def normalize(op):
    import anticheat_policy
    op = dict(op or {})
    pieces = tuple(op.get('pieces') or STANDARD)
    bad_ones = sorted(set(pieces) - set(PARTS))
    if bad_ones:
        raise SystemExit('anti-cheat piece %s: not one of %s' % (', '.join(bad_ones), ', '.join(PARTS)))
    action_codes = tuple(op['action_codes']) if op.get('action_codes') is not None else ('warn',)
    bad_ones = sorted(set(action_codes) - set(anticheat_policy.ACTIONS))
    if bad_ones:
        raise SystemExit(
            'anti-cheat action %s: not one of %s' % (', '.join(bad_ones), ', '.join(anticheat_policy.ACTIONS))
        )
    method = op.get('codes_mode') or 'auto'
    if method not in CODES_MODES:
        raise SystemExit('anti-cheat codes mode %r: not one of %s' % (method, ', '.join(CODES_MODES)))
    try:
        jump = int(op['gold_jump']) if op.get('gold_jump') not in (None, '') else 400
        per_pack = int(op['per_pack']) if op.get('per_pack') not in (None, '') else 4
    except (TypeError, ValueError):
        raise SystemExit('anti-cheat: the gold jump and the decoys per pack have to be whole numbers')
    if jump < 1 or per_pack < 1 or per_pack > 50:
        raise SystemExit('anti-cheat: the gold jump has to be 1 or more and the decoys per pack 1..50')
    return {
        'pieces': pieces,
        'action_codes': action_codes,
        'gold_jump': jump,
        'codes_mode': method,
        'per_pack': per_pack,
    }


def applies(body_text, language, pieces=STANDARD, action_codes=('warn',), gold_jump=400, codes_mode='auto', per_pack=4,
            hook=None, ref=None):
    import anticheat_policy
    hook = hook or anticheat_policy.HOOK
    if language not in ('jass', 'lua'):
        raise ValueError('language has to be jass or lua, not %r' % (language,))
    bad_ones = sorted(set(pieces) - set(PARTS))
    if bad_ones:
        raise ValueError('piece %s: not one of %s' % (', '.join(bad_ones), ', '.join(PARTS)))
    if codes_mode not in CODES_MODES:
        raise ValueError('codes mode %r: not one of %s' % (codes_mode, ', '.join(CODES_MODES)))
    as_bytes = isinstance(body_text, bytes)
    if as_bytes:
        body_text = body_text.decode('utf-8', 'surrogateescape')
    original = body_text
    details = {'ok': True, 'piece': 'anticheat', 'language': language, 'pieces': {}, 'keep_names': [], 'line_list': [],
               'action_codes': [], 'applied': False, 'policy': None}
    chosen = [p for p in ORDER[language] if p in set(pieces)]
    options = {'gold_jump': int(gold_jump), 'codes_mode': codes_mode, 'per_pack': int(per_pack)}
    if any(p in chosen for p in ('ledger', 'codes', 'bj')):
        body_text, policy_report = anticheat_policy.inject(body_text, language, action_codes=action_codes, hook=hook)
        details['policy'] = policy_report
        details['action_codes'] = policy_report['action_codes']
        details['line_list'].append(policy_report['summary'])
    for fname in chosen:
        try:
            new, r = _part(fname, body_text, language, hook, options, ref)
        except Exception as e:
            why = ('%s: %s' % (type(e).__name__, e) if not isinstance(e, (ValueError, RuntimeError)) else str(e))[:300]
            details['pieces'][fname] = {'status': 'skipped', 'why': why}
            details['line_list'].append('%s: skipped (%s)' % (fname, why))
            continue
        changed, why = _effect(fname, r)
        if not changed:
            details['pieces'][fname] = {'status': 'no effect', 'why': why, 'stats': r}
            details['line_list'].append('%s: nothing to do (%s)' % (fname, why or 'no change'))
            continue
        body_text = new
        details['pieces'][fname] = {'status': 'ok', 'stats': r}
        if fname == 'decoys':
            details['keep_names'] = list(r.get('keep_names') or [])
            details['line_list'] += (r.get('line_list') or [])[:1]
        else:
            details['line_list'].append('%s: %s' % (fname, r.get('summary') or 'ok'))
    if not any(v['status'] == 'ok' for v in details['pieces'].values()):
        body_text = original
        details['policy'] = None
        details['action_codes'] = []
    details['applied'] = body_text != original
    details['bytes'] = len(body_text.encode('utf-8', 'surrogateescape')) - len(
        original.encode('utf-8', 'surrogateescape')
    )
    if as_bytes:
        body_text = body_text.encode('utf-8', 'surrogateescape')
    return body_text, details
