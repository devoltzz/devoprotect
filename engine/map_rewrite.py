# Adds code to a map script, checks it with pjass and writes the new map, checked file by file.
import re




def insert(text, tree, globals_lines=(), functions='', main_top=(), main_end=()):
    parts = re.split(r'(\r\n?|\n)', text)
    lines = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else '') for i in range(0, len(parts), 2)]
    nl = '\r\n' if text.count('\r\n') * 2 > text.count('\n') else '\n'
    main = tree.function_index.get('main')
    if main is None or main.is_native:
        raise ValueError('the script has no function main')
    edits = []
    if main_end:
        edits.append((main.end_line - 1, list(main_end)))
    if main_top:
        after = max([main.line] + [l.line for l in main.locals])
        edits.append((after, list(main_top)))
    if functions:
        edits.append((main.line - 1, functions.rstrip('\n').split('\n') + ['']))
    if globals_lines:
        block = next((it for it in tree.items if type(it).__name__ == 'Globals'), None)
        if block is not None:
            edits.append((block.end_line - 1, list(globals_lines)))
        else:
            first = next((it for it in tree.items if type(it).__name__ == 'Function' and not it.is_native),
                         main)
            edits.append((first.line - 1, ['globals'] + list(globals_lines) + ['endglobals']))
    for at, new in sorted(edits, key=lambda e: -e[0]):
        lines[at:at] = [l + nl for l in new]
    return ''.join(lines)

