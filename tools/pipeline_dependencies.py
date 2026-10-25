"""Isolated test IdP and deterministic model; never records requests or credentials."""
import http.server
import json
import pathlib
import ssl
import threading
import time

ROOT = pathlib.Path('/fixture')
LOCK = threading.Lock()
CALLS = 0


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == '/jwks.json':
            return self.reply(200, json.loads((ROOT/'jwks.json').read_text()))
        if self.path == '/api/tags':
            return self.reply(200, {'models': [{'name': 'qualification-model', 'model': 'qualification-model'}]})
        if self.path == '/counts':
            return self.reply(200, {'modelCalls': CALLS})
        self.reply(404, {})

    def do_POST(self):
        global CALLS
        length = int(self.headers.get('Content-Length', '0'))
        if self.path != '/api/chat' or not 0 < length <= 1048576:
            return self.reply(400, {})
        request = json.loads(self.rfile.read(length))
        with LOCK:
            CALLS += 1
        deadline = time.monotonic()+30
        while (ROOT/'hold-model').exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if (ROOT/'hold-model').exists():
            return self.reply(503, {'error': 'Fixture model deadline'})
        self.reply(200, {'model': request.get('model'), 'done': True,
                        'message': {'role': 'assistant', 'content': (ROOT/'reply.txt').read_text()}})


if __name__ == '__main__':
    secure = http.server.ThreadingHTTPServer(('0.0.0.0', 8443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ROOT/'server.crt', ROOT/'server.key')
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    threading.Thread(target=secure.serve_forever, daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0', 11434), Handler).serve_forever()
