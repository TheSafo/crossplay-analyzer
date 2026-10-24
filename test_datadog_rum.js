const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const { runInNewContext } = require('node:vm');

const source = readFileSync(`${__dirname}/datadog-rum.js`, 'utf8');

function loadRum({
  applicationId = 'REPLACE_WITH_TEST_APPLICATION_ID',
  clientToken = 'REPLACE_WITH_TEST_CLIENT_TOKEN',
  sdkReady = false
} = {}) {
  // Inject synthetic values so these checks keep working after the real public
  // credentials are filled in, without loading the SDK or sending telemetry.
  const code = source
    .replace(/^  const applicationId = .*;$/m, `  const applicationId = ${JSON.stringify(applicationId)};`)
    .replace(/^  const clientToken = .*;$/m, `  const clientToken = ${JSON.stringify(clientToken)};`);
  const scripts = [];
  let config;
  const sdk = { init(value) { config = value; } };
  const window = { location: { origin: 'https://crossplay.example' } };
  if (sdkReady) window.DD_RUM = { ...sdk, onReady(callback) { callback(); } };
  const document = {
    createElement(tag) { assert.equal(tag, 'script'); return {}; },
    head: { appendChild(script) { scripts.push(script); } }
  };
  runInNewContext(code, { window, document, URL });
  // Simulate the asynchronous CDN replacing the stub and draining its queue.
  if (window.DD_RUM && !sdkReady) {
    const queue = window.DD_RUM.q;
    window.DD_RUM = sdk;
    queue.forEach(callback => callback());
  }
  return { scripts, config };
}

test('no CDN or telemetry until both public RUM credentials are filled in', () => {
  for (const credentials of [
    {}, { applicationId: 'test-app' }, { clientToken: 'test-token' },
    { applicationId: '', clientToken: 'test-token' },
    { applicationId: 'test-app', clientToken: '' }
  ]) {
    const { scripts, config } = loadRum(credentials);
    assert.equal(scripts.length, 0);
    assert.equal(config, undefined);
  }
});

test('all entry pages load shared RUM config before application scripts', () => {
  for (const page of ['index.html', 'screenshot.html', 'manual.html']) {
    const html = readFileSync(`${__dirname}/${page}`, 'utf8');
    assert.match(html, /<head>[\s\S]*?<script src="datadog-rum\.js"><\/script>[\s\S]*?<\/head>/);
    assert.equal(html.indexOf('<script'), html.indexOf('<script src="datadog-rum.js">'));
    assert.equal(html.split('src="datadog-rum.js"').length, 2);
  }
  const html = readFileSync(`${__dirname}/index.html`, 'utf8');
  assert.match(html, /<form[^>]*id="cookieForm"[^>]*data-dd-privacy="hidden"/);
  assert.match(html, /<input[^>]*id="cookieInput"[^>]*type="password"/);
});

for (const sdkReady of [false, true]) {
  test(`RUM uses US5, masks inputs and disables replay (SDK ready: ${sdkReady})`, () => {
    const { scripts, config } = loadRum({ applicationId: 'test-app', clientToken: 'test-token', sdkReady });
    assert.equal(scripts.length, 1);
    assert.equal(scripts[0].async, true);
    assert.equal(scripts[0].src, 'https://www.datadoghq-browser-agent.com/us5/v6/datadog-rum.js');
    assert.equal(config.applicationId, 'test-app');
    assert.equal(config.clientToken, 'test-token');
    assert.equal(config.site, 'us5.datadoghq.com');
    assert.equal(config.service, 'crossplay-analyzer');
    assert.equal(config.env, 'production');
    assert.equal(config.defaultPrivacyLevel, 'mask');
    assert.equal(config.sessionReplaySampleRate, 0);
    assert.equal(config.trackUserInteractions, false);
    assert.equal(config.trackResources, true);
  });
}

test('trace propagation is limited to the same-origin Crossplay API', () => {
  const { config } = loadRum({ applicationId: 'test-app', clientToken: 'test-token' });
  assert.equal(config.allowedTracingUrls.length, 1);
  const tracing = config.allowedTracingUrls[0];
  assert.deepEqual(Array.from(tracing.propagatorTypes), ['datadog', 'tracecontext']);
  for (const url of [
    '/api/crossplay', '/api/crossplay?route=status', '/api/crossplay/status',
    'https://crossplay.example/api/crossplay/games/test/review'
  ]) assert.equal(tracing.match(url), true, url);
  for (const url of [
    '/api/crossplay-other', '/api/other', '/quackle.wasm',
    'https://other.example/api/crossplay/status',
    'https://crossplay.example.other.example/api/crossplay/status',
    'http://crossplay.example/api/crossplay/status',
    'https://crossplay.example:444/api/crossplay/status',
    '//www.nytimes.com/api/crossplay/status'
  ]) assert.equal(tracing.match(url), false, url);
});
