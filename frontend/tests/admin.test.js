import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

// Read the Python literal without importing server configuration or credentials.
const html = execFileSync('python3', ['-c', `
import ast, pathlib, sys
module = ast.parse(pathlib.Path(sys.argv[1]).read_text())
for node in module.body:
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ADMIN_PAGE' for target in node.targets):
        print(ast.literal_eval(node.value))
        break
else:
    raise RuntimeError('ADMIN_PAGE was not found')
`, fileURLToPath(new URL('../../server/main.py', import.meta.url))], { encoding: 'utf8' })
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1])
const tick = () => new Promise(resolve => setImmediate(resolve))

function stats(overrides = {}) {
  return {
    release: 'test-release', version: 'demo1', status: 'ok', processed_at: '2026-11-02 11:30:00',
    uptime_seconds: 120, checks: { frontend: { ok: true, built: true } }, interface_errors: [],
    stats: { requests: { total: 7, errors: 0, recent: { total: 2, errors: 0 } }, events: {}, observations: {}, paths: [], errors: [] },
    ...overrides,
  }
}

async function dashboard(response = stats()) {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(([, id]) => [id, {
    innerHTML: '', textContent: '', hidden: false, open: false, listeners: {},
    addEventListener(type, handler) { this.listeners[type] = handler },
  }]))
  const requests = []
  const fixture = { response, elements, requests }
  const context = vm.createContext({
    document: {
      hidden: false,
      getElementById: id => elements.get(id),
      querySelectorAll: () => [],
      addEventListener() {},
    },
    setInterval() {},
    fetch: async url => {
      requests.push(url)
      if (url === '/api/admin/stats') {
        if (fixture.response instanceof Error) throw fixture.response
        return { ok: true, json: async () => fixture.response }
      }
      if (url === '/api/admin/summary') return { ok: true, json: async () => ({ today: 3, total: 9, generated: 8 }) }
      if (url === '/api/admin/sessions?limit=30') return { ok: true, json: async () => ({ enabled: true, total: 0, retention_days: 7, sessions: [] }) }
      throw new Error('Unexpected request: ' + url)
    },
  })
  assert.ok(scripts.length, 'the dashboard must contain an executable script')
  scripts.forEach((source, index) => new vm.Script(source, { filename: `admin-inline-${index}.js` }).runInContext(context))
  await tick()
  return fixture
}

test('admin boots its script and keeps an empty error bar visible', async () => {
  const { elements, requests } = await dashboard()
  assert.deepEqual(requests, ['/api/admin/stats', '/api/admin/sessions?limit=30', '/api/admin/summary'])
  assert.match(elements.get('meta-updated').textContent, /更新于 2026-11-02/)
  assert.match(elements.get('summary').innerHTML, /今日体验/)
  assert.match(elements.get('requests').innerHTML, /请求总数<\/span><b>7/)
  assert.match(elements.get('status').innerHTML, /全部正常/)
  assert.match(elements.get('sessions').innerHTML, /还没有会话记录/)
  assert.match(elements.get('errors').innerHTML, /暂无错误/)
  assert.equal(elements.get('alert').hidden, false)
  assert.match(elements.get('alert').innerHTML, /暂无接口错误/)
  assert.doesNotMatch(elements.get('alert').className, /\balert\b/)
})

test('admin shows recent interface errors and keeps history after refreshing', async () => {
  const recent = { at: '11:29:00', path: '/api/journey/illustrate', status: 503, code: 'illustrate_quota' }
  const older = { at: '10:00:00', path: '/api/journey/compose/stream', status: 502, code: 'text_timeout' }
  const data = stats({ interface_errors: [recent] })
  data.stats.errors = [recent, older]
  const fixture = await dashboard(data)
  const banner = fixture.elements.get('alert')
  assert.equal(banner.hidden, false)
  assert.match(banner.className, /\balert\b/)
  for (const value of [recent.at, recent.path, 'HTTP 503', recent.code, '插画服务额度不足']) assert.ok(banner.innerHTML.includes(value))
  assert.ok(!banner.innerHTML.includes(older.code))
  assert.match(fixture.elements.get('errors').innerHTML, /text_timeout/)
  banner.open = true
  await fixture.elements.get('refresh').listeners.click()
  assert.equal(banner.open, true, 'refresh must preserve expanded error details')
  fixture.response = { ...data, interface_errors: [] }
  await fixture.elements.get('refresh').listeners.click()
  assert.equal(banner.hidden, false)
  assert.equal(banner.open, false)
  assert.match(banner.innerHTML, /暂无接口错误/)
  assert.match(fixture.elements.get('errors').innerHTML, /illustrate_quota/)
})

test('admin includes current API failures even when request history is empty', async () => {
  const fixture = await dashboard(stats({ checks: {
    text: { ok: false, primary_ok: false, balance: -0.02, model: 'deepseek-chat', fallback: 'qwen-plus' },
    image: { ok: false, detail: '额度不足' },
    frontend: { ok: false, built: false },
    disk: { ok: false, percent: 98, free_gb: 1 },
  } }))
  const banner = fixture.elements.get('alert')
  assert.match(banner.innerHTML, /当前 · 文本模型：主模型不可用（余额 -0.02）/)
  assert.match(banner.innerHTML, /qwen-plus/)
  assert.match(banner.innerHTML, /插画服务：额度不足/)
  assert.doesNotMatch(banner.innerHTML, /前端构建|磁盘/)
  fixture.response = stats({ checks: { text: { ok: true, model: 'deepseek-chat' } } })
  await fixture.elements.get('refresh').listeners.click()
  assert.match(banner.innerHTML, /暂无接口错误/)
})

test('admin escapes interface error text in the banner and history', async () => {
  const error = { at: '11:29:00', path: '/api/<img src=x onerror=alert(1)>', status: 503, code: '<script>alert(1)</script>' }
  const data = stats({ interface_errors: [error] })
  data.stats.errors = [error]
  const { elements } = await dashboard(data)
  for (const id of ['alert', 'errors']) {
    assert.match(elements.get(id).innerHTML, /&lt;script&gt;/)
    assert.doesNotMatch(elements.get(id).innerHTML, /<script>|<img /)
  }
})

test('admin shows a fetch failure and the refresh button recovers the data', async () => {
  const fixture = await dashboard(new Error('network unavailable'))
  const banner = fixture.elements.get('alert')
  assert.equal(banner.hidden, false)
  assert.match(banner.innerHTML, /看板数据读取失败：network unavailable/)
  assert.match(fixture.elements.get('summary').innerHTML, /今日体验/)
  fixture.response = stats()
  await fixture.elements.get('refresh').listeners.click()
  assert.equal(banner.hidden, false)
  assert.match(banner.innerHTML, /暂无接口错误/)
  assert.match(fixture.elements.get('requests').innerHTML, /请求总数/)
})
