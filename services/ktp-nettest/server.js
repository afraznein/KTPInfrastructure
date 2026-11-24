'use strict';
// ktp-nettest: per-region connection test node. See README.md and the coordination design
// research/netcode-player-settings/DESIGN_connection-test_20261025.md.
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { verify } = require('./lib/ticket');
const { makeBusy } = require('./lib/busy');

const MAX_MB = 25;
const STALL_MAX_S = 90;          // a stall session is torn down after this, whatever the browser does
const GATHER_MAX_MS = 5000;      // host candidates only, so gathering is near-instant when it works
const CHUNK = crypto.randomBytes(64 * 1024);  // incompressible; reused for every download
// The stall test's pacing clock; client.js says why it runs in a worker.
const TICK_WORKER = 'setInterval(() => postMessage(0), 10);';

function config(env = process.env) {
  const ports = (env.KTP_NETTEST_UDP_PORTS || '').split('-').map(Number);
  return {
    port: Number(env.KTP_NETTEST_PORT || 8790),
    host: env.KTP_NETTEST_BIND || '0.0.0.0',
    region: env.KTP_NETTEST_REGION || '',
    secret: env.KTP_NETTEST_TICKET_SECRET || '',
    origin: env.KTP_NETTEST_ORIGIN || 'https://ktpleague.gg',
    logDirs: (env.KTP_NETTEST_LOG_DIRS || '').split(':').filter(Boolean),
    udpPorts: ports.length === 2 && ports[0] < ports[1] ? ports : undefined,
    maxStalls: Number(env.KTP_NETTEST_MAX_STALLS || 4),
    maxTransfers: Number(env.KTP_NETTEST_MAX_TRANSFERS || 2),
  };
}

// The shipped example secret, and anything too short to be a generated one, must not start a
// node: a node signing with a guessable secret accepts tickets anyone can mint.
const SECRET_MIN_LEN = 32;
function startupProblem(cfg) {
  if (!cfg.region || !cfg.secret) return 'KTP_NETTEST_REGION and KTP_NETTEST_TICKET_SECRET are required';
  if (/placeholder|replace|changeme/i.test(cfg.secret)) return 'KTP_NETTEST_TICKET_SECRET is still the example placeholder';
  if (cfg.secret.length < SECRET_MIN_LEN) return `KTP_NETTEST_TICKET_SECRET is shorter than ${SECRET_MIN_LEN} characters`;
  return null;
}

const escAttr = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// The page the website frames. Its CSP is the second wall: only this node's own scripts run, they
// talk only to this node, and only the website may embed it.
function framePage(origin) {
  return '<!doctype html><html><head><meta charset="utf-8">' +
    `<meta name="ktp-parent-origin" content="${escAttr(origin)}">` +
    '<script src="/client.js"></script><script src="/frame.js"></script></head><body></body></html>';
}
const frameCsp = (origin) =>
  `default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors ${origin}`;

// Browsers hide host candidates behind mDNS .local names that resolve only on the player's LAN.
// werift starts a multicast-dns responder for them, which throws outside any request and kills the node.
const isMdnsCandidate = (l) => l.startsWith('a=candidate:') && (l.split(' ')[4] || '').includes('.local');
function dropMdnsCandidates(sdp) {
  const lines = sdp.split('\n');
  if (!lines.some(isMdnsCandidate)) return sdp;
  // Without end-of-candidates werift waits for the browser's checks and pairs it as peer-reflexive.
  return lines.filter((l) => !isMdnsCandidate(l) && !l.startsWith('a=end-of-candidates')).join('\n');
}

function createServer(cfg, { isBusy = makeBusy(cfg.logDirs), RTCPeerConnection = null } = {}) {
  const spent = new Map();
  let stalls = 0, transfers = 0;

  const send = (res, status, body, type = 'application/json') => {
    res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' });
    res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
  };

  async function stallOffer(sdp) {
    const PC = RTCPeerConnection || require('werift').RTCPeerConnection;
    const pc = new PC({ iceServers: [], icePortRange: cfg.udpPorts, iceUseIpv6: false });
    stalls++;
    let closed = false;
    const close = () => { if (!closed) { closed = true; stalls--; clearTimeout(timer); pc.close().catch(() => {}); } };
    const timer = setTimeout(close, STALL_MAX_S * 1000).unref();
    pc.onDataChannel.subscribe((dc) => {
      // Echo each packet with the node's receive time appended; the browser does the arithmetic.
      dc.onMessage.subscribe((msg) => {
        if (!Buffer.isBuffer(msg) || msg.length > 64) return;
        const out = Buffer.alloc(msg.length + 8);
        msg.copy(out);
        out.writeDoubleBE(Date.now(), msg.length);
        try { dc.send(out); } catch { /* channel closing */ }
      });
      dc.stateChanged.subscribe((s) => { if (s === 'closed') close(); });
    });
    pc.connectionStateChange.subscribe((s) => { if (s === 'failed' || s === 'closed') close(); });
    try {
      await pc.setRemoteDescription({ type: 'offer', sdp: dropMdnsCandidates(sdp) });
      await pc.setLocalDescription(await pc.createAnswer());
      // Non-trickle: answer once host candidates are in. Public game hosts need no STUN.
      // werift swallows a gathering failure and never reaches 'complete', so the wait needs a bound.
      if (pc.iceGatheringState !== 'complete') {
        await new Promise((ok, no) => {
          const t = setTimeout(() => no(new Error('ICE gathering did not complete')), GATHER_MAX_MS);
          pc.iceGatheringStateChange.subscribe((s) => { if (s === 'complete') { clearTimeout(t); ok(); } });
        });
      }
      return pc.localDescription.sdp;
    } catch (e) { close(); throw e; }
  }

  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    res.setHeader('access-control-allow-origin', cfg.origin);
    res.setHeader('vary', 'origin');
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'access-control-allow-methods': 'GET, POST',
        'access-control-allow-headers': 'content-type',
        'access-control-max-age': '600',
      });
      return res.end();
    }
    const route = `${req.method} ${url.pathname}`;
    // client.js is served beside the API so the website loads the exact build this node speaks.
    if (route === 'GET /client.js') {
      res.setHeader('access-control-allow-origin', '*');
      return send(res, 200, fs.readFileSync(path.join(__dirname, 'client.js')), 'text/javascript');
    }
    if (route === 'GET /frame') {
      res.setHeader('content-security-policy', frameCsp(cfg.origin));
      return send(res, 200, framePage(cfg.origin), 'text/html; charset=utf-8');
    }
    if (route === 'GET /frame.js') return send(res, 200, fs.readFileSync(path.join(__dirname, 'frame.js')), 'text/javascript');
    if (route === 'GET /tick.js') return send(res, 200, TICK_WORKER, 'text/javascript');
    if (route === 'GET /busy') return send(res, 200, { region: cfg.region, busy: isBusy() });
    if (!['GET /ping', 'GET /down', 'POST /up', 'POST /stall/offer'].includes(route)) return send(res, 404, { error: 'not found' });

    // Busy first: a refused run must not spend the player's 10-minute slot.
    if (isBusy()) return send(res, 409, { busy: true, until: 'live match' });
    // Ticket in the query string keeps GETs "simple" CORS requests: no preflight inside a ping.
    const v = verify(cfg.secret, url.searchParams.get('t'), { region: cfg.region, spent });
    if (!v.ok) return send(res, v.status || 401, { error: v.why });

    if (route === 'GET /ping') { res.writeHead(204, { 'cache-control': 'no-store' }); return res.end(); }

    if (route === 'POST /stall/offer') {
      if (stalls >= cfg.maxStalls) return send(res, 503, { error: 'node is full, retry shortly' });
      let sdp = '';
      for await (const c of req) { sdp += c; if (sdp.length > 16384) return send(res, 413, { error: 'offer too large' }); }
      try { return send(res, 200, { sdp: await stallOffer(sdp) }); } catch { return send(res, 400, { error: 'bad offer' }); }
    }

    if (transfers >= cfg.maxTransfers) return send(res, 503, { error: 'node is full, retry shortly' });
    transfers++;
    res.on('close', () => { transfers--; });
    if (route === 'GET /down') {
      const mb = Math.min(MAX_MB, Math.max(1, Number(url.searchParams.get('mb')) || 1));
      res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': mb * 1024 * 1024, 'cache-control': 'no-store' });
      let left = mb * 16;  // 64 KiB chunks
      const pump = () => { while (left > 0) { left--; if (!res.write(CHUNK)) return res.once('drain', pump); } res.end(); };
      return pump();
    }
    // POST /up: count and discard, refuse past the cap.
    let n = 0;
    for await (const c of req) { n += c.length; if (n > MAX_MB * 1024 * 1024) { req.destroy(); return; } }
    return send(res, 200, { bytes: n });
  });
}

if (require.main === module) {
  const cfg = config();
  const problem = startupProblem(cfg);
  if (problem) { console.error(problem); process.exit(2); }
  if (!cfg.logDirs.length) console.error('warning: KTP_NETTEST_LOG_DIRS empty, node reports busy (never loads an unknown box)');
  createServer(cfg).listen(cfg.port, cfg.host, () => console.log(`ktp-nettest ${cfg.region} on ${cfg.host}:${cfg.port}`));
}

module.exports = { createServer, config, framePage, frameCsp, startupProblem, dropMdnsCandidates };
