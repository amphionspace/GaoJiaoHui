import unittest

from server.metrics import Metrics


class MetricsTests(unittest.TestCase):
    def test_requests_track_counts_errors_and_percentiles(self):
        metrics = Metrics()
        for status in (200, 200, 500):
            metrics.request('/api/journey/compose/stream', status, 0.2)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot['requests']['total'], 3)
        self.assertEqual(snapshot['requests']['errors'], 1)
        path = snapshot['paths'][0]
        self.assertEqual(path['path'], '/api/journey/compose/stream')
        self.assertEqual(path['count'], 3)
        self.assertEqual(path['errors'], 1)
        self.assertEqual(path['p50_ms'], 200.0)
        self.assertEqual(path['statuses'], {'200': 2, '500': 1})

    def test_events_and_observations_are_aggregated(self):
        metrics = Metrics()
        metrics.event('compose_draft')
        metrics.event('compose_draft')
        metrics.observe('compose_draft_seconds', 1.5)
        metrics.observe('compose_draft_seconds', 2.5)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot['events']['compose_draft'], 2)
        series = snapshot['observations']['compose_draft_seconds']
        self.assertEqual(series['count'], 2)
        self.assertEqual(series['p50_ms'], 2000.0)
        self.assertEqual(series['last_ms'], 2500.0)

    def test_prometheus_exposition_contains_health_and_events(self):
        metrics = Metrics()
        metrics.request('/api/journey/compose/stream', 200, 1.2)
        metrics.event('compose_final')
        body = metrics.prometheus()
        self.assertIn('journey_http_requests_total{path="/api/journey/compose/stream",status="200"} 1', body)
        self.assertIn('journey_events_total{event="compose_final"} 1', body)
        self.assertIn('journey_uptime_seconds', body)

    def test_errors_are_bounded_and_carry_no_payload(self):
        metrics = Metrics()
        for index in range(60):
            metrics.error('/api/journey/compose/stream', 504, 'text_timeout')
        snapshot = metrics.snapshot()
        self.assertEqual(len(snapshot['errors']), 40)
        self.assertEqual(set(snapshot['errors'][0]), {'at', 'path', 'status', 'code'})


if __name__ == '__main__':
    unittest.main()
