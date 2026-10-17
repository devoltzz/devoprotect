# The real progress of a job: nested scopes with counts, which the page learns the length of.
import contextlib


_emit = None
_stack = []
def file_path():
    return '/'.join(n for n, _r in _stack)


def _send(label_text, done=None, total=None):
    if _emit is None:
        return
    ev = {'type': 'progress', 'label': label_text, 'path': file_path()}
    if total:
        ev['done'] = max(0, min(int(done or 0), int(total)))
        ev['total'] = int(total)
    try:
        _emit(ev)
    except Exception:
        pass


@contextlib.contextmanager
def stage(fname, label_text=None):
    label_text = label_text or (_stack[-1][1] if _stack else fname)
    _stack.append((fname, label_text))
    stack_depth = len(_stack)
    _send(label_text)
    try:
        yield
    finally:
        if len(_stack) >= stack_depth and _stack[stack_depth - 1][0] == fname:
            del _stack[stack_depth - 1:]
            if _stack:
                _send(_stack[-1][1])

