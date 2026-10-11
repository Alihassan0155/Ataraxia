"""Local queue for authenticated individual-file downloads; URLs stay in memory."""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from materialize_drive_downloads import DESTINATION, download

TASKS = queue.Queue()
LOCK = threading.Lock()
STATE = {'queued': 0, 'completed': 0, 'failed': 0, 'active': 0, 'bytes': 0, 'errors': []}
SEEN = set()


def worker():
    while True:
        item = TASKS.get()
        if item is None:
            TASKS.task_done()
            return
        with LOCK:
            STATE['active'] += 1
        try:
            result = download(item)
        except Exception as error:
            result = {'id': item['id'], 'name': item['name'], 'status': 'failed', 'error_type': type(error).__name__}
        with LOCK:
            with (DESTINATION / 'download_status.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(result) + '\n')
            STATE['active'] -= 1
            if result['status'] == 'failed':
                STATE['failed'] += 1
                STATE['errors'].append(result)
            else:
                STATE['completed'] += 1
                STATE['bytes'] += int(result.get('size', 0))
            if (STATE['completed'] + STATE['failed']) % 25 == 0:
                print(json.dumps(STATE), flush=True)
        TASKS.task_done()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != '/status':
            self.send_error(404)
            return
        with LOCK:
            body = json.dumps(STATE).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 2 * 1024 * 1024:
            self.send_error(413)
            return
        if self.path == '/enqueue':
            items = json.loads(self.rfile.read(length))
            with LOCK:
                for item in items:
                    if item['id'] not in SEEN:
                        SEEN.add(item['id'])
                        STATE['queued'] += 1
                        TASKS.put(item)
            self.send_response(200); self.end_headers(); self.wfile.write(b'queued')
        elif self.path == '/finish':
            self.send_response(200); self.end_headers(); self.wfile.write(b'finishing')
            def finish():
                TASKS.join()
                for _ in range(8):
                    TASKS.put(None)
                TASKS.join()
                (DESTINATION / 'transfer_summary.json').write_text(json.dumps(STATE, indent=2) + '\n')
                self.server.shutdown()
            threading.Thread(target=finish, daemon=True).start()
        else:
            self.send_error(404)


if __name__ == '__main__':
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        threading.Thread(target=worker, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(json.dumps({'port': server.server_port}), flush=True)
    server.serve_forever()
    server.server_close()
    print(json.dumps(STATE), flush=True)
