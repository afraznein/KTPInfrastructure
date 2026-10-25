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
const CHUNK = crypto.randomBytes(64 * 1024);  // incompressible; reused for every download

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
      await pc.setRemoteDescription({ type: 'offer', sdp });
      await pc.setLocalDescription(await pc.createAnswer());
      // Non-trickle: answer once host candidates are in. Public game hosts need no STUN.
      if (pc.iceGatheringState !== 'complete') {
        await new Promise((ok) => pc.iceGatheringStateChange.subscribe((s) => { if (s === 'complete') ok(); }));
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
  if (!cfg.region || !cfg.secret) { console.error('KTP_NETTEST_REGION and KTP_NETTEST_TICKET_SECRET are required'); process.exit(2); }
  if (!cfg.logDirs.length) console.error('warning: KTP_NETTEST_LOG_DIRS empty, node reports busy (never loads an unknown box)');
  createServer(cfg).listen(cfg.port, cfg.host, () => console.log(`ktp-nettest ${cfg.region} on ${cfg.host}:${cfg.port}`));
}

module.exports = { createServer, config };
