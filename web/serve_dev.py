# Serves a built site on this computer with the headers of the real host, for testing.
import functools
import http.server
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = {'.wasm': 'application/wasm', '.mjs': 'text/javascript', '.js': 'text/javascript',
         '.webmanifest': 'application/manifest+json', '.whl': 'application/zip', '.npz': 'application/octet-stream'}


def headers():
    with open(os.path.join(HERE, 'deploy', 'headers.conf'), encoding='utf-8') as f:
        return re.findall(r'^add_header ([\w-]+) "([^"]*)"', f.read(), re.M)


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES)
    data = None
    sent = headers()

    def translate_path(self, path):
        if self.data and path.split('?', 1)[0].startswith('/data/'):
            name = os.path.basename(path.split('?', 1)[0])
            return os.path.join(self.data, name)
        return super().translate_path(path)

    def end_headers(self):
        for k, v in self.sent:
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, *args):
        pass


USAGE = 'usage: python web/serve_dev.py --site=<built site> [--data=<folder with game_data.zip>] [--port=8616]'


def main(argv):
    op = dict((a[2:].split('=', 1) + [''])[:2] for a in argv if a.startswith('--'))
    if not op.get('site'):
        print(USAGE)
        return 2
    Handler.data = os.path.abspath(op['data']) if op.get('data') else None
    port = int(op.get('port') or 8616)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port),
                                             functools.partial(Handler, directory=os.path.abspath(op['site'])))
    print('http://127.0.0.1:%d/ (%s)' % (port, op['site']))
    server.serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
