import json
from datetime import date, timedelta
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
        'week_start': '2026-09-07',
        'week_end': '2026-09-13',
        'created': 1,
        'updated': 1,
    }]
    range_reports = [
        dict(reports[0]),
        {'id': 'report-late', 'title': '年末周报',
         'week_start': '2026-12-28', 'week_end': '2027-01-03', 'created': 3, 'updated': 3},
        {'id': 'report-early', 'title': '跨月周报',
         'week_start': '2026-07-27', 'week_end': '2026-08-02', 'created': 2, 'updated': 2},
    ]

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/weekly':
            limit = parse_qs(parsed.query).get('limit')
            if limit is None:
                self.respond_json(self.range_reports)
                return
            if limit not in (['1'], ['5']):
                self.send_error(400)
                return
            self.respond_json(self.reports)
        elif parsed.path in ('/api/weekly/report-1/people', '/api/weekly/report-early/people'):
            self.respond_json(['张三', '李四'])
        elif parsed.path == '/api/weekly/report-late/people':
            self.respond_json(['李四'])
        elif parsed.path == '/api/weekly/bad-json/people':
            self.respond(b'not json', 'application/json')
        elif parsed.path in ('/api/weekly/report-1/export',
                              '/api/weekly/report-early/export',
                              '/api/weekly/report-late/export'):
            query = parse_qs(parsed.query)
            view = query.get('view')
            if view not in (['project'], ['person']):
                self.send_error(400)
                return
            person = query.get('person')
            if person and person != ['张三']:
                self.respond_json({'error': '人员不存在：' + person[0]}, 404)
                return
            titles = {'report-1': '研发周报', 'report-early': '跨月周报', 'report-late': '年末周报'}
            report_id = parsed.path.split('/')[3]
            body = '# ' + titles[report_id] + '\n' + ('\n## 张三\n完成内容\n' if person else '')
            self.respond(body.encode('utf-8'), 'text/markdown; charset=utf-8')
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

    def test_export_without_id_uses_report_containing_today(self):
        original = WeeklyHandler.range_reports
        today = date.today()
        WeeklyHandler.range_reports = [
            {'id': 'report-late', 'title': '年末周报',
             'week_start': (today + timedelta(days=7)).isoformat(),
             'week_end': (today + timedelta(days=13)).isoformat(), 'created': 3, 'updated': 3},
            {'id': 'report-1', 'title': '研发周报',
             'week_start': (today - timedelta(days=2)).isoformat(),
             'week_end': (today + timedelta(days=4)).isoformat(), 'created': 1, 'updated': 1},
        ]
        try:
            result = self.run_cli('export')
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout.decode('utf-8'), '# 研发周报\n')

            WeeklyHandler.range_reports = [WeeklyHandler.range_reports[0]]
            result = self.run_cli('export')
            self.assertEqual(result.returncode, 1)
            self.assertIn('没有对应的周报', result.stderr.decode('utf-8'))
        finally:
            WeeklyHandler.range_reports = original

    def test_export_can_filter_by_person(self):
        result = self.run_cli('export', 'report-1', '--person', '张三')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn('## 张三', result.stdout.decode('utf-8'))

        result = self.run_cli('export', 'report-1', '--person', '王五')
        self.assertEqual(result.returncode, 1)
        self.assertIn('HTTP 404：人员不存在：王五', result.stderr.decode('utf-8'))

    def test_export_date_range_includes_overlaps_and_sorts_oldest_first(self):
        result = self.run_cli('export', '--start-time', '20260801', '--end-time', '20261231')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode('utf-8')
        titles = ['# 跨月周报', '# 研发周报', '# 年末周报']
        self.assertEqual([text.index(title) for title in titles], sorted(text.index(title) for title in titles))
        self.assertEqual(text.count('\n---\n'), 2)

    def test_export_month_year_aliases_and_person_filter(self):
        result = self.run_cli('export', '--month', '202608')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn('# 跨月周报', result.stdout.decode('utf-8'))
        self.assertNotIn('# 研发周报', result.stdout.decode('utf-8'))

        result = self.run_cli('export', '--year', '2026', '--person', '张三')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode('utf-8')
        self.assertIn('# 跨月周报', text)
        self.assertIn('# 研发周报', text)
        self.assertNotIn('# 年末周报', text)

    def test_export_rejects_invalid_or_conflicting_periods(self):
        cases = [
            ('--start-time', '20260101'),
            ('--month', '202613'),
            ('--year', '20x6'),
            ('--start-time', '20261231', '--end-time', '20260101'),
            ('--month', '202608', '--year', '2026'),
            ('report-1', '--year', '2026'),
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_cli('export', *args)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.decode('utf-8').startswith('错误：'))

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
