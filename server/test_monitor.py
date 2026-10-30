import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import monitor


def health(status='ok', **checks):
    body = {'status': status, 'checks': {}}
    for name, value in checks.items():
        body['checks'][name] = value if isinstance(value, dict) else {'ok': value}
    return body


class MonitorTests(unittest.TestCase):
    def test_failed_checks_become_notifications(self):
        parsed = monitor.checks_from(health('degraded', disk={'ok': False, 'percent': 98, 'free_gb': 21}))
        self.assertEqual(parsed, [('disk', False, '磁盘 98%（剩余 21G）')])

    def test_degraded_status_without_a_failed_check_alerts_the_service(self):
        self.assertEqual(monitor.checks_from(health('degraded')), [('service', False, '健康状态 degraded')])
        self.assertEqual(monitor.checks_from(health('ok')), [])

    def test_alert_is_sent_once_and_reminded_after_ten_minutes(self):
        state = {}
        failing = [('disk', False, '磁盘 98%')]
        self.assertEqual(monitor.decide(state, failing, 1000.0), [('alert', 'disk', '磁盘 98%')])
        state['checks']['disk']['sent'] = 1000.0
        self.assertEqual(monitor.decide(state, failing, 1060.0), [])
        self.assertEqual(monitor.decide(state, failing, 1601.0), [('alert', 'disk', '磁盘 98%')])
        state['checks']['disk']['sent'] = 1601.0
        self.assertEqual(monitor.decide(state, [('disk', True, '')], 1700.0), [('recover', 'disk', '')])
        self.assertEqual(monitor.decide(state, [('disk', True, '')], 1800.0), [])

    def test_webhook_payload_is_wecom_markdown(self):
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return b'{"errcode":0,"errmsg":"ok"}'

        def fake_urlopen(request, timeout):
            seen['url'] = request.full_url
            seen['body'] = json.loads(request.data)
            seen['timeout'] = timeout
            return Response()

        with patch.object(monitor.urllib.request, 'urlopen', fake_urlopen):
            sent = monitor.send_webhook('https://example.test/hook', '**告警**')

        self.assertTrue(sent)
        self.assertEqual(seen['url'], 'https://example.test/hook')
        self.assertEqual(seen['body']['msgtype'], 'markdown')
        self.assertEqual(seen['body']['markdown']['content'], '**告警**')

    def test_webhook_rejection_and_failure_are_reported_without_the_url(self):
        class Rejected:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return b'{"errcode":93000,"errmsg":"invalid webhook"}'

        with patch.object(monitor.urllib.request, 'urlopen', lambda *args, **kwargs: Rejected()):
            self.assertFalse(monitor.send_webhook('https://example.test/hook', 'x'))
        with patch.object(monitor.urllib.request, 'urlopen', side_effect=OSError('boom')):
            self.assertFalse(monitor.send_webhook('https://example.test/hook', 'x'))

    def test_missing_webhook_leaves_state_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'monitor.json'
            with patch.object(monitor, 'load_health', return_value=health('ok')):
                code = monitor.run('http://unused', str(state_path), '')
            self.assertEqual(code, 0)
            self.assertFalse(state_path.exists())

    def test_alert_run_writes_state_and_only_notifies_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'monitor.json'
            failing = health('degraded', disk={'ok': False, 'percent': 98, 'free_gb': 21})
            with patch.object(monitor, 'load_health', return_value=failing), \
                 patch.object(monitor, 'send_webhook', return_value=True) as send:
                monitor.run('http://unused', str(state_path), 'https://example.test/hook')
                monitor.run('http://unused', str(state_path), 'https://example.test/hook')
            self.assertEqual(send.call_count, 1)
            saved = json.loads(state_path.read_text())
            self.assertTrue(saved['checks']['disk']['active'])
            self.assertGreater(saved['checks']['disk']['sent'], 0)


if __name__ == '__main__':
    unittest.main()


class MonitorRetryTests(unittest.TestCase):
    def test_unreachable_health_is_retried_once(self):
        calls = []

        def fake(url, timeout=5):
            calls.append(url)
            if len(calls) == 1:
                raise OSError('boom')
            return health('ok')

        with patch.object(monitor, 'load_health', fake), patch.object(monitor.time, 'sleep'):
            self.assertEqual(monitor.load_health_retry('http://unused'), health('ok'))
        self.assertEqual(len(calls), 2)
