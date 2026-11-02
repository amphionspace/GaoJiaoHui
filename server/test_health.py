import base64
import unittest
from unittest.mock import patch

import httpx

from server import main

ADMIN_ENV = {'JOURNEY_ADMIN_USER': 'admin', 'JOURNEY_ADMIN_PASSWORD': 'test-admin-password', 'JOURNEY_ADMIN_IPS': ''}


def basic():
    token = base64.b64encode(b'admin:test-admin-password').decode()
    return {'Authorization': 'Basic ' + token}


class InterfaceProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._health_recorded.clear()
        main.metrics_store.errors.clear()

    async def test_probe_reports_healthy_routes(self):
        with patch.object(main, 'PROBE_ROUTES', (('GET', '/api/config', None), ('GET', '/', None))):
            result = await main.api_check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['checked'], 2)
        self.assertEqual(result['failed'], [])
        self.assertEqual(result['detail'], '接口可用')

    async def test_probe_flags_a_broken_route(self):
        with patch.object(main.managed_asr, 'enabled', side_effect=RuntimeError('boom')), \
             patch.object(main, 'PROBE_ROUTES', (('GET', '/api/config', None),)):
            result = await main.api_check()
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], ['/api/config'])
        self.assertIn('/api/config', result['detail'])

    def test_failed_probe_is_recorded_once_and_rearms_after_recovery(self):
        failing = {'api': {'ok': False, 'checked': 7, 'failed': ['/api/journey/compose'],
                           'detail': '/api/journey/compose HTTP 500'}}
        main.record_health_failures(failing)
        main.record_health_failures(failing)
        errors = [item for item in main.metrics_store.recent_errors(900) if item['code'] == 'api_unavailable']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['path'], '/api/journey/compose')
        main.record_health_failures({'api': {'ok': True, 'failed': [], 'detail': '接口可用'}})
        main.record_health_failures(failing)
        self.assertEqual(len([item for item in main.metrics_store.recent_errors(900)
                              if item['code'] == 'api_unavailable']), 2)

    def test_other_checks_are_recorded_against_their_interface(self):
        main.record_health_failures({'text': {'ok': False, 'model': '', 'fallback': ''}})
        errors = main.metrics_store.recent_errors(900)
        self.assertEqual(errors[0]['path'], '/api/journey/compose/stream')
        self.assertEqual(errors[0]['code'], 'health_text')

    async def test_probe_failure_reaches_the_admin_interface_errors(self):
        failing = {'ok': False, 'checked': 7, 'failed': ['/api/journey/illustrate'],
                   'detail': '/api/journey/illustrate HTTP 503'}
        with patch.object(main, 'api_check', return_value=failing), patch.dict('os.environ', ADMIN_ENV):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                         base_url='http://127.0.0.1:8766') as api:
                health = await api.get('/api/health')
                stats = await api.get('/api/admin/stats', headers=basic())
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.json()['checks']['api']['ok'])
        data = stats.json()
        self.assertEqual(data['status'], 'degraded')
        self.assertTrue(any(item['code'] == 'api_unavailable' and
                            item['path'] == '/api/journey/illustrate'
                            for item in data['interface_errors']))
        self.assertTrue(any('接口可用性' in item for item in data['alerts']))

    async def test_probe_requests_are_not_counted_as_visitor_traffic(self):
        before = main.metrics_store.snapshot()['requests']['total']
        await main.api_check()
        self.assertEqual(main.metrics_store.snapshot()['requests']['total'], before)


if __name__ == '__main__':
    unittest.main()
