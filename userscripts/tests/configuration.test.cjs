const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'immobilienmonitor-browser-energy.user.js'), 'utf8');
const SERVER = 'immobilien_monitor_server_base_url';
const ENERGY = 'immobilien_energy_api_token';
const BROWSER = 'immobilien_browser_enrich_token';

function load(storage = new Map(), answers = [], confirm = true) {
    const requests = [];
    const prompts = [];
    const instrumented = source.replace('    const initialInfo = portalInfo();', `
    showBrowserStatus = () => {};
    globalThis.api = {normalizeServerBase, getServerBase, serverEndpoint,
        configureServer, resetTokenMenu, sendToMonitor, sendBrowserEnrichment};
    return;
    const initialInfo = portalInfo();`);
    const context = vm.createContext({
        URL, console,
        location: { hostname: 'www.immowelt.de', pathname: '/expose/test-123' },
        GM_getValue: (key, fallback) => storage.has(key) ? storage.get(key) : fallback,
        GM_setValue: (key, value) => storage.set(key, value),
        GM_registerMenuCommand() {},
        GM_xmlhttpRequest(options) {
            requests.push(options);
            options.onload?.({ status: 200, responseText: '{"ok":true}' });
        },
        window: {
            prompt(message) { prompts.push(message); return answers.shift() ?? null; },
            confirm() { return confirm; }, alert() {},
            setTimeout() { return 1; }, setInterval() { return 1; },
            clearInterval() {},
        },
    });
    vm.runInContext(instrumented, context);
    return { api: context.api, storage, requests, prompts };
}

test('only an HTTPS origin can be configured', () => {
    const { api } = load();
    assert.equal(api.normalizeServerBase(' HTTPS://MONITOR.EXAMPLE.ORG:8443/ '), 'https://monitor.example.org:8443');
    for (const value of ['', 'garbage', 'http://monitor.example.org', 'javascript:alert(1)',
        'https://user:password@monitor.example.org', 'https://monitor.example.org/path',
        'https://monitor.example.org/?key=secret', 'https://monitor.example.org/#secret',
        'https://monitor.example.invalid']) {
        assert.equal(api.normalizeServerBase(value), '', value);
    }
});

test('no configured server means no requests and no token prompts', async () => {
    const { api, requests, prompts } = load(new Map([[ENERGY, 'saved-e'], [BROWSER, 'saved-b']]));
    await assert.rejects(api.sendToMonitor({}, {}), /Server fehlt/);
    api.sendBrowserEnrichment({ portal: 'immowelt', portal_id: 'test-123' });
    assert.equal(requests.length, 0);
    assert.equal(prompts.length, 0);
});

test('stored server and tokens survive a script reload', async () => {
    const storage = new Map([[ENERGY, 'saved-e'], [BROWSER, 'saved-b']]);
    load(storage, ['https://monitor.example.org:8443/']).api.configureServer();
    const { api, requests } = load(storage);
    assert.equal(api.getServerBase(), 'https://monitor.example.org:8443');
    await api.sendToMonitor({ portal: 'immowelt', portalId: 'test-123' }, {});
    api.sendBrowserEnrichment({ portal: 'immowelt', portal_id: 'test-123' });
    assert.equal(requests[0].url, 'https://monitor.example.org:8443/immobilien-energy/energy');
    assert.equal(requests[0].headers.Authorization, 'Bearer saved-e');
    assert.equal(requests[1].url, 'https://monitor.example.org:8443/browser-enrich');
    assert.equal(requests[1].headers['X-Browser-Enrich-Token'], 'saved-b');
});

test('server changes require confirmation and clear tokens', () => {
    const storage = new Map([[SERVER, 'https://old.example.org'], [ENERGY, 'saved-e'], [BROWSER, 'saved-b']]);
    load(storage, ['https://new.example.org'], false).api.configureServer();
    assert.equal(storage.get(SERVER), 'https://old.example.org');
    assert.equal(storage.get(ENERGY), 'saved-e');
    load(storage, ['https://new.example.org']).api.configureServer();
    assert.equal(storage.get(SERVER), 'https://new.example.org');
    assert.equal(storage.get(ENERGY), '');
    assert.equal(storage.get(BROWSER), '');
});

test('cancel, invalid input and unchanged server preserve stored settings', () => {
    const storage = new Map([[SERVER, 'https://monitor.example.org'], [ENERGY, 'saved-e'], [BROWSER, 'saved-b']]);
    for (const value of [null, 'http://unsafe.example.org', 'https://monitor.example.org/']) {
        load(storage, [value]).api.configureServer();
        assert.equal(storage.get(SERVER), 'https://monitor.example.org');
        assert.equal(storage.get(ENERGY), 'saved-e');
        assert.equal(storage.get(BROWSER), 'saved-b');
    }
});

test('both download paths and update metadata identify the same release', () => {
    const dir = path.join(__dirname, '..');
    assert.equal(source, fs.readFileSync(path.join(dir, 'immobilien-energy.user.js'), 'utf8'));
    const metadata = fs.readFileSync(path.join(dir, 'immobilienmonitor-browser-energy.meta.js'), 'utf8');
    assert.ok(source.startsWith(metadata.trimEnd()));
    assert.match(metadata, /@version\s+1\.3\.7\n/);
    assert.match(metadata, /@updateURL\s+https:\/\/raw\.githubusercontent\.com\/flamingsnowflake\/GPT-ImmoRadar\/main\/userscripts\/immobilienmonitor-browser-energy\.meta\.js/);
    assert.match(metadata, /@downloadURL\s+https:\/\/raw\.githubusercontent\.com\/flamingsnowflake\/GPT-ImmoRadar\/main\/userscripts\/immobilienmonitor-browser-energy\.user\.js/);
    assert.doesNotMatch(source, /BEGIN .*PRIVATE KEY|bot\d{5,}:[A-Za-z0-9_-]+/i);
});
