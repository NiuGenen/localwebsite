import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse


SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'weekly.py'


class WeeklyHandler(BaseHTTPRequestHandler):
    reports = [{
        'id': 'report-1',
        'title': '研发周报',
        'description': '本周进展',
        'week_start': '2026-09-07',
        'week_end': '2026-09-13',
        'created': 1,
        'updated': 1,
    }]

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/weekly':
            if parse_qs(parsed.query).get('limit') not in (['1'], ['5']):
                self.send_error(400)
                return
            self.respond_json(self.reports)
        elif parsed.path == '/api/weekly/report-1/people':
            self.respond_json(['张三', '李四'])
        elif parsed.path == '/api/weekly/bad-json/people':
            self.respond(b'not json', 'application/json')
        elif parsed.path == '/api/weekly/report-1/export':
            view = parse_qs(parsed.query).get('view')
            if view not in (['project'], ['person']):
                self.send_error(400)
                return
            self.respond('# 研发周报\n'.encode('utf-8'), 'text/markdown; charset=utf-8')
        else:
            self.respond_json({'error': '周报不存在'}, 404)

    def respond_json(self, value, status=200):
        self.respond(json.dumps(value, ensure_ascii=False).encode('utf-8'),
                     'application/json; charset=utf-8', status)

    def respond(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class WeeklyCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), WeeklyHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_cli(self, *args):
        command = [sys.executable, str(SCRIPT), '--server', self.base_url, *args]
        return subprocess.run(command, capture_output=True)

    def test_default_list_and_json_output(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode('utf-8')
        self.assertIn('report-1', text)
        self.assertIn('研发周报', text)

        result = self.run_cli('list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)[0]['id'], 'report-1')

    def test_help_lists_supported_operations(self):
        result = self.run_cli('help')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode('utf-8')
        for command in ('list', 'people', 'export', 'help'):
            self.assertIn(command, text)
        self.assertIn('显示脚本支持的操作', text)

    def test_people_and_export_to_stdout_or_file(self):
        result = self.run_cli('people', 'report-1')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode('utf-8'), '张三\n李四\n')

        result = self.run_cli('people', 'report-1', '--json')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout), ['张三', '李四'])

        result = self.run_cli('export', 'report-1', '--view', 'person')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode('utf-8'), '# 研发周报\n')

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'report.md'
            result = self.run_cli('export', 'report-1', '-o', str(destination))
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout, b'')
            self.assertEqual(destination.read_text(encoding='utf-8'), '# 研发周报\n')

    def test_export_without_id_uses_latest_report(self):
        result = self.run_cli('export')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode('utf-8'), '# 研发周报\n')

    def test_http_error_is_reported(self):
        result = self.run_cli('people', 'missing')
        self.assertEqual(result.returncode, 1)
        self.assertIn('HTTP 404：周报不存在', result.stderr.decode('utf-8'))

    def test_invalid_json_and_connection_error_are_reported(self):
        result = self.run_cli('people', 'bad-json')
        self.assertEqual(result.returncode, 1)
        self.assertIn('服务器返回了无效的 JSON', result.stderr.decode('utf-8'))

        command = [sys.executable, str(SCRIPT), '--server', 'http://127.0.0.1:1',
                   '--timeout', '0.2', 'people', 'report-1']
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('无法连接服务器', result.stderr.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
