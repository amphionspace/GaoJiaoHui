"""In-process request and journey metrics for the ops dashboard and /metrics.

Only aggregates are kept: no transcript, audio, key or user text ever reaches
this module. Counters reset when the service restarts, which the dashboard and
the docs state explicitly.
"""
import math
import threading
import time
from collections import Counter, deque

MAX_PATHS = 24
MAX_ERRORS = 40
DURATION_WINDOW = 300
RECENT_WINDOW = 300
RECENT_MAX = 600


def _percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.paths = {}
        self.events = Counter()
        self.observations = {}
        self.errors = deque(maxlen=MAX_ERRORS)
        self.recent = deque(maxlen=RECENT_MAX)

    def _path(self, path):
        entry = self.paths.get(path)
        if entry:
            return entry
        if len(self.paths) >= MAX_PATHS:
            path = '(other)'
            entry = self.paths.get(path)
            if entry:
                return entry
        entry = self.paths[path] = {
            'count': 0, 'errors': 0, 'statuses': Counter(),
            'durations': deque(maxlen=DURATION_WINDOW), 'seconds': 0.0,
        }
        return entry

    def request(self, path, status, seconds):
        now = time.time()
        with self.lock:
            entry = self._path(path)
            entry['count'] += 1
            entry['seconds'] += seconds
            entry['durations'].append(seconds)
            entry['statuses'][str(status)] += 1
            if status >= 500:
                entry['errors'] += 1
            self.recent.append((now, status))

    def event(self, name, count=1):
        with self.lock:
            self.events[name] += count

    def observe(self, name, seconds):
        with self.lock:
            series = self.observations.setdefault(name, deque(maxlen=DURATION_WINDOW))
            series.append(max(0.0, seconds))

    def error(self, path, status, code=''):
        with self.lock:
            self.errors.appendleft({
                'at': time.strftime('%H:%M:%S', time.localtime()),
                'path': path, 'status': status, 'code': str(code)[:60],
            })

    def _recent(self):
        cutoff = time.time() - RECENT_WINDOW
        while self.recent and self.recent[0][0] < cutoff:
            self.recent.popleft()
        total = len(self.recent)
        errors = sum(1 for _, status in self.recent if status >= 500)
        return {'window_seconds': RECENT_WINDOW, 'total': total, 'errors': errors}

    def snapshot(self):
        with self.lock:
            paths = []
            for path, entry in self.paths.items():
                durations = list(entry['durations'])
                paths.append({
                    'path': path,
                    'count': entry['count'],
                    'errors': entry['errors'],
                    'statuses': dict(entry['statuses']),
                    'p50_ms': round((_percentile(durations, .5) or 0) * 1000, 1),
                    'p95_ms': round((_percentile(durations, .95) or 0) * 1000, 1),
                    'avg_ms': round((entry['seconds'] / entry['count'] * 1000) if entry['count'] else 0, 1),
                })
            paths.sort(key=lambda item: item['count'], reverse=True)
            observations = {}
            for name, series in self.observations.items():
                values = list(series)
                observations[name] = {
                    'count': len(values),
                    'p50_ms': round((_percentile(values, .5) or 0) * 1000, 1),
                    'p95_ms': round((_percentile(values, .95) or 0) * 1000, 1),
                    'last_ms': round((values[-1] if values else 0) * 1000, 1),
                }
            return {
                'started_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.started)),
                'uptime_seconds': round(time.time() - self.started),
                'requests': {
                    'total': sum(entry['count'] for entry in self.paths.values()),
                    'errors': sum(entry['errors'] for entry in self.paths.values()),
                    'recent': self._recent(),
                },
                'paths': paths,
                'events': dict(self.events),
                'observations': observations,
                'errors': list(self.errors),
            }

    def prometheus(self):
        lines = [
            '# HELP journey_uptime_seconds Seconds since the app process started.',
            '# TYPE journey_uptime_seconds gauge',
            f'journey_uptime_seconds {round(time.time() - self.started)}',
        ]
        snapshot = self.snapshot()
        lines += ['# HELP journey_http_requests_total HTTP requests by path and status.',
                  '# TYPE journey_http_requests_total counter']
        for path in snapshot['paths']:
            for status, count in path['statuses'].items():
                lines.append(f'journey_http_requests_total{{path="{path["path"]}",status="{status}"}} {count}')
        lines += ['# HELP journey_http_request_duration_seconds Request duration in seconds.',
                  '# TYPE journey_http_request_duration_seconds summary']
        for path in snapshot['paths']:
            lines.append(f'journey_http_request_duration_seconds{{path="{path["path"]}",quantile="0.5"}} {path["p50_ms"] / 1000}')
            lines.append(f'journey_http_request_duration_seconds{{path="{path["path"]}",quantile="0.95"}} {path["p95_ms"] / 1000}')
            lines.append(f'journey_http_request_duration_seconds_count{{path="{path["path"]}"}} {path["count"]}')
            lines.append(f'journey_http_request_duration_seconds_sum{{path="{path["path"]}"}} {path["avg_ms"] / 1000 * path["count"]}')
        lines += ['# HELP journey_events_total Journey stage events.',
                  '# TYPE journey_events_total counter']
        for name, count in sorted(snapshot['events'].items()):
            lines.append(f'journey_events_total{{event="{name}"}} {count}')
        return '\n'.join(lines) + '\n'


metrics = Metrics()
