'use strict';
// Real server, real werift answer, client.js driving it with werift standing in for the browser.
const test = require('node:test');
const assert = require('node:assert');
const werift = require('werift');
const { createServer } = require('../server');
const { mint } = require('../lib/ticket');
const { runTest } = require('../client');

// Browser-shaped facade over werift: ArrayBuffer in and out, on* properties.
class BrowserPC {
  constructor() { this.pc = new werift.RTCPeerConnection(); }
  createDataChannel(label, opts) {
    const dc = this.pc.createDataChannel(label, opts);
    const face = {
      get readyState() { return dc.readyState; },
      onopen: null, onmessage: null,
      send: (b) => dc.send(Buffer.from(b)),
      close: () => dc.close(),
    };
    dc.stateChanged.subscribe((s) => { if (s === 'open' && face.onopen) face.onopen(); });
    dc.onMessage.subscribe((m) => {
      if (face.onmessage) face.onmessage({ data: m.buffer.slice(m.byteOffset, m.byteOffset + m.byteLength) });
    });
    return face;
  }
  get iceGatheringState() { return this.pc.iceGatheringState; }
  get localDescription() { return this.pc.localDescription; }
  addEventListener(ev, fn) { if (ev === 'icegatheringstatechange') this.pc.iceGatheringStateChange.subscribe(fn); }
  createOffer() { return this.pc.createOffer(); }
  setLocalDescription(d) { return this.pc.setLocalDescription(d); }
  setRemoteDescription(d) { return this.pc.setRemoteDescription(d); }
  close() { this.pc.close(); }
}

async function withServer(opts, fn) {
  const cfg = { region: 'NY', secret: 's', origin: 'https://ktpleague.gg', maxStalls: 4, maxTransfers: 2 };
  const srv = createServer(cfg, opts);
  await new Promise((ok) => srv.listen(0, '127.0.0.1', ok));
  try { return await fn(`http://127.0.0.1:${srv.address().port}`); } finally { srv.close(); srv.closeAllConnections(); }
}
const ticket = (pid = 1, jti = 'x') => mint('s', { jti, pid, region: 'NY', exp: Date.now() / 1000 + 300 });

test('full run: stall, ping, bandwidth', { timeout: 60000 }, () => withServer({ isBusy: () => false }, async (base) => {
  const phases = new Set();
  const r = await runTest({ base, ticket: ticket(), stallSeconds: 2, mb: 2, RTCPeerConnection: BrowserPC, fetch, onProgress: (p) => phases.add(p.phase) });
  assert.strictEqual(r.stall_sent, 200);
  assert.ok(r.stall_loss_pct < 5, `loopback loss ${r.stall_loss_pct}%`);
  assert.strictEqual(r.stall_gaps_250, 0);
  assert.ok(r.ping_ms !== null && r.down_mbps > 0 && r.up_mbps > 0, JSON.stringify(r));
  assert.strictEqual(r.busy_skipped, false);
  assert.deepStrictEqual([...phases], ['stall', 'ping', 'download', 'upload', 'done']);
}));

let busy = false;
test('gates: no ticket 401, busy 409, second run inside 10 min 429, busy route open', () => withServer({ isBusy: () => busy }, async (base) => {
  assert.strictEqual((await fetch(`${base}/ping`)).status, 401);
  assert.strictEqual((await fetch(`${base}/ping?t=${ticket(2, 'a')}`)).status, 204);
  assert.strictEqual((await fetch(`${base}/ping?t=${ticket(2, 'b')}`)).status, 429);
  busy = true;
  assert.strictEqual((await fetch(`${base}/ping?t=${ticket(3, 'c')}`)).status, 409);
  const b = await fetch(`${base}/busy`);
  busy = false;
  assert.strictEqual((await fetch(`${base}/ping?t=${ticket(3, 'd')}`)).status, 204, 'busy refusal did not spend the slot');
  busy = true;
  assert.strictEqual(b.headers.get('access-control-allow-origin'), 'https://ktpleague.gg');
  assert.deepStrictEqual(await b.json(), { region: 'NY', busy: true });
  assert.strictEqual((await fetch(`${base}/client.js`)).status, 200);
  assert.strictEqual((await fetch(`${base}/up?t=${ticket(3, 'c')}`, { method: 'GET' })).status, 404);
}));

test('region turning busy after the stall test skips the rest, keeps the stall result', { timeout: 60000 }, () => {
  let calls = 0;
  // Busy from the first non-stall request onward.
  return withServer({ isBusy: () => calls++ > 0 }, async (base) => {
    const r = await runTest({ base, ticket: ticket(4), stallSeconds: 1, mb: 1, RTCPeerConnection: BrowserPC, fetch });
    assert.strictEqual(r.busy_skipped, true);
    assert.strictEqual(r.stall_sent, 100);
    assert.strictEqual(r.down_mbps, undefined);
  });
});
