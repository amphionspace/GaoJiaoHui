import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from server import main, sessions as session_store

ADMIN_ENV = {'JOURNEY_ADMIN_USER': 'admin', 'JOURNEY_ADMIN_PASSWORD': 'test-admin-password', 'JOURNEY_ADMIN_IPS': ''}


def basic(user='admin', password='test-admin-password'):
    token = base64.b64encode((user + ':' + password).encode()).decode()
    return {'Authorization': 'Basic ' + token}


def client(host='127.0.0.1', client_host='127.0.0.1'):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, client=(client_host, 12345)),
                             base_url='http://' + host + ':8766')


class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_is_disabled_without_credentials(self):
        with patch.dict('os.environ', {'JOURNEY_ADMIN_USER': '', 'JOURNEY_ADMIN_PASSWORD': ''}):
            async with client() as api:
                response = await api.get('/admin', headers=basic())
        self.assertEqual(response.status_code, 503)
        self.assertIn('后台未启用', response.text)

    async def test_admin_requires_basic_auth(self):
        with patch.dict('os.environ', ADMIN_ENV):
            async with client() as api:
                missing = await api.get('/admin')
                wrong = await api.get('/admin', headers=basic(password='wrong'))
                allowed = await api.get('/admin', headers=basic())
        self.assertEqual(missing.status_code, 401)
        self.assertIn('Basic realm="journey-admin"', missing.headers['www-authenticate'])
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn('运维看板', allowed.text)
        self.assertEqual(allowed.headers['cache-control'], 'no-store')

    async def test_stats_expose_aggregates_without_content(self):
        with patch.dict('os.environ', ADMIN_ENV):
            async with client() as api:
                response = await api.get('/api/admin/stats', headers=basic())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['version'], 'demo1')
        self.assertEqual(data['release'], main.os.path.basename(main.ROOT))
        self.assertIn('checks', data)
        self.assertIn('stats', data)
        text = response.text
        for secret in ('test-admin-password', 'api_key', 'transcript'):
            self.assertNotIn(secret, text)

    async def test_metrics_are_protected_and_expose_health_gauges(self):
        with patch.dict('os.environ', ADMIN_ENV):
            async with client() as api:
                denied = await api.get('/metrics')
                allowed = await api.get('/metrics', headers=basic())
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn('journey_health_ok{check="text"}', allowed.text)
        self.assertIn('journey_disk_used_ratio', allowed.text)

    async def test_optional_ip_allowlist_uses_forwarded_address_behind_the_local_proxy(self):
        env = {**ADMIN_ENV, 'JOURNEY_ADMIN_IPS': '203.0.113.9'}
        with patch.dict('os.environ', env):
            async with client(client_host='127.0.0.1') as api:
                forwarded = await api.get('/admin', headers={**basic(), 'X-Forwarded-For': '203.0.113.9'})
                blocked = await api.get('/admin', headers={**basic(), 'X-Forwarded-For': '198.51.100.7'})
            async with client(client_host='198.51.100.7') as api:
                direct = await api.get('/admin', headers={**basic(), 'X-Forwarded-For': '203.0.113.9'})
        self.assertEqual(forwarded.status_code, 200)
        self.assertEqual(blocked.status_code, 403)
        # A non-local peer cannot spoof the allowlist with a forwarded header.
        self.assertEqual(direct.status_code, 403)

    async def test_health_reports_checks_and_recent_counters(self):
        async with client() as api:
            response = await api.get('/api/health')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['version'], 'demo1')
        self.assertIn('checks', data)
        for name in ('frontend', 'text', 'asr', 'tts', 'disk'):
            self.assertIn(name, data['checks'])
        self.assertIn('recent', data['stats'])
        self.assertIn(data['status'], ('ok', 'degraded'))

    async def test_admin_sessions_are_protected_and_clearable(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**ADMIN_ENV, 'JOURNEY_SESSION_LOG': '1',
                   'JOURNEY_SESSION_DB': str(Path(directory) / 'sessions.sqlite3')}
            request = SimpleNamespace(transcript='我想让爸爸省点力。', topic='future', language='zh')
            note = SimpleNamespace(note_text='我想让爸爸省点力。', message='你想让爸爸少弯一点腰。', keywords=['爸爸'])
            with patch.dict('os.environ', env):
                session_store.record_draft('one', request, note, 1200, 'deepseek-chat')
                async with client() as api:
                    denied = await api.get('/api/admin/sessions')
                    allowed = await api.get('/api/admin/sessions', headers=basic())
                    cleared = await api.post('/api/admin/sessions/clear', headers=basic())
                self.assertEqual(denied.status_code, 401)
                self.assertEqual(allowed.status_code, 200)
                data = allowed.json()
                self.assertTrue(data['enabled'])
                self.assertEqual(data['total'], 1)
                self.assertEqual(data['sessions'][0]['transcript'], request.transcript)
                self.assertEqual(data['sessions'][0]['draft_ms'], 1200)
                self.assertEqual(cleared.status_code, 200)
                self.assertEqual(session_store.count(), 0)


if __name__ == '__main__':
    unittest.main()


class AdminSummaryAndAudioTests(unittest.IsolatedAsyncioTestCase):
    def env(self, directory):
        return {**ADMIN_ENV, 'JOURNEY_SESSION_LOG': '1',
                'JOURNEY_SESSION_DB': str(Path(directory) / 'sessions.sqlite3'),
                'JOURNEY_SESSION_AUDIO_DIR': str(Path(directory) / 'audio'),
                'JOURNEY_SESSION_AUDIO': '1', 'JOURNEY_ACCESS_KEY': 'test-key'}

    @staticmethod
    def wav():
        import io
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as sample:
            sample.setnchannels(1)
            sample.setsampwidth(2)
            sample.setframerate(24000)
            sample.writeframes(b'\x00\x00' * 24000)
        return buffer.getvalue()

    async def test_summary_and_audio_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory)):
                session_store.save_audio('c' * 32, 'reply', self.wav())
                session_store.save_audio('c' * 32, 'visit', self.wav())
                async with client() as api:
                    denied = await api.get('/api/admin/summary')
                    summary = await api.get('/api/admin/summary', headers=basic())
                    audio = await api.get('/api/admin/sessions/' + 'c' * 32 + '/audio/reply', headers=basic())
                    visit = await api.get('/api/admin/sessions/' + 'c' * 32 + '/audio/visit', headers=basic())
                    missing = await api.get('/api/admin/sessions/' + 'c' * 32 + '/audio/sample', headers=basic())
                    bad_kind = await api.get('/api/admin/sessions/' + 'c' * 32 + '/audio/other', headers=basic())
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()['audio'], 1)
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers['content-type'], 'audio/wav')
        self.assertEqual(visit.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_kind.status_code, 404)

    async def test_print_event_marks_the_session(self):
        request = SimpleNamespace(transcript='我想让爸爸省点力。', topic='future', language='zh')
        note = SimpleNamespace(note_text='我想让爸爸省点力。', message='你想让爸爸少弯一点腰。', keywords=['爸爸'])
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', self.env(directory)):
                session_store.record_draft('d' * 32, request, note, 100, 'deepseek-chat')
                async with client() as api:
                    response = await api.post('/api/journey/print', headers={'X-API-Key': 'test-key'},
                                              json={'session_id': 'd' * 32})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['printed'])
                self.assertEqual(session_store.summary()['printed'], 1)
