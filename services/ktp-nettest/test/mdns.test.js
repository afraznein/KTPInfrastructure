'use strict';
// A real browser hides its host candidates behind mDNS ".local" names. werift answers those by
// starting a multicast-dns responder, whose socket callback calls os.networkInterfaces() outside any
// request; under the unit's RestrictAddressFamilies that threw EAFNOSUPPORT and killed the node.
const test = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const crypto = require('node:crypto');
const path = require('node:path');
const werift = require('werift');
const { createServer } = require('../server');
const { mint } = require('../lib/ticket');
const { runTest } = require('../client');

// werift's ice.js reads MdnsLookup off this module at call time, so swapping the export intercepts it.
const lookupMod = require(path.join(path.dirname(require.resolve('werift')), '../../ice/src/dns/lookup.js'));
const RealMdns = lookupMod.MdnsLookup;
let mdnsStarted = 0;
class FakeMdns {
  // Same shape as multicast-dns: the interface lookup runs later, in a socket callback no request owns.
  constructor() { mdnsStarted++; setImmediate(() => os.networkInterfaces()); }
  lookup() { return Promise.reject(new Error('No mDNS response')); }
  close() {}
}
test.before(() => { lookupMod.MdnsLookup = FakeMdns; });
test.after(() => { lookupMod.MdnsLookup = RealMdns; });

const toMdns = (sdp) => sdp.replace(/^(a=candidate:\S+ \d+ \S+ \d+ )(\S+)/gm, (_, head) => `${head}${crypto.randomUUID()}.local`);

// Browser-shaped facade over werift whose offer carries only .local host candidates, as Chrome's does.
class MdnsBrowserPC {
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
  get localDescription() { const d = this.pc.localDescription; return d && { type: d.type, sdp: toMdns(d.sdp) }; }
  addEventListener(ev, fn) { if (ev === 'icegatheringstatechange') this.pc.iceGatheringStateChange.subscribe(fn); }
  createOffer() { return this.pc.createOffer(); }
  setLocalDescription(d) { return this.pc.setLocalDescription(d); }
  setRemoteDescription(d) { return this.pc.setRemoteDescription(d); }
  close() { this.pc.close(); }
}

async function withServer(fn) {
  const cfg = { region: 'NY', secret: 's', origin: 'https://ktpleague.gg', maxStalls: 4, maxTransfers: 2 };
  const srv = createServer(cfg, { isBusy: () => false });
  await new Promise((ok) => srv.listen(0, '127.0.0.1', ok));
  try { return await fn(`http://127.0.0.1:${srv.address().port}`); } finally { srv.close(); srv.closeAllConnections(); }
}
const ticket = (pid, jti) => mint('s', { jti, pid, region: 'NY', exp: Date.now() / 1000 + 300 });

test('an offer with only .local candidates never starts mDNS and still connects', { timeout: 30000 }, () => withServer(async (base) => {
  mdnsStarted = 0;
  const r = await runTest({ base, ticket: ticket(1, 'm1'), stallSeconds: 1, mb: 1, RTCPeerConnection: MdnsBrowserPC, fetch });
  assert.strictEqual(mdnsStarted, 0, 'werift started an mDNS responder for a browser candidate');
  assert.strictEqual(r.stall_sent, 100);
  assert.ok(r.stall_loss_pct < 5, `loopback loss ${r.stall_loss_pct}%`);
}));

test('an interface lookup refused with EAFNOSUPPORT fails one offer and the node keeps serving', { timeout: 30000 }, () => withServer(async (base) => {
  mdnsStarted = 0;
  const client = new werift.RTCPeerConnection();
  client.createDataChannel('stall');
  await client.setLocalDescription(await client.createOffer());
  if (client.iceGatheringState !== 'complete') {
    await new Promise((ok) => client.iceGatheringStateChange.subscribe((s) => s === 'complete' && ok()));
  }
  const offer = toMdns(client.localDescription.sdp);
  await client.close();

  const uncaught = [];
  const onUncaught = (e) => uncaught.push(e);
  process.on('uncaughtException', onUncaught);
  const realIfaces = os.networkInterfaces;
  os.networkInterfaces = () => {
    const e = new Error('uv_interface_addresses returned Unknown system error 97');
    e.code = 'ERR_SYSTEM_ERROR';
    throw e;
  };
  try {
    const res = await fetch(`${base}/stall/offer?t=${ticket(2, 'm2')}`, { method: 'POST', body: offer });
    await new Promise((ok) => setTimeout(ok, 200));
    os.networkInterfaces = realIfaces;
    assert.strictEqual(res.status, 400);
    assert.deepStrictEqual(uncaught.map((e) => e.message), []);
    assert.strictEqual((await fetch(`${base}/busy`)).status, 200);
  } finally {
    os.networkInterfaces = realIfaces;
    process.removeListener('uncaughtException', onUncaught);
  }
}));
