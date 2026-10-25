// ktp-nettest browser client. One file, no build: load with <script src="https://<node>/client.js">
// (sets window.KtpNettest) or require() it in Node for tests.
//
//   const r = await KtpNettest.runTest({ base: 'https://ny.nettest.example:8790', ticket, onProgress });
//
// `r` carries the measured columns of ktp.connection_test; the page adds the player's said_* picks
// and posts the row to the website (never to the node). Every number is from the browser's clock.
(function (root) {
  'use strict';
  const GAP_MS = 250;
  const VERSION = 'ktp-nettest-client/1';

  function median(xs) {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  const meanStep = (xs) => {
    let j = 0;
    for (let i = 1; i < xs.length; i++) j += Math.abs(xs[i] - xs[i - 1]);
    return xs.length > 1 ? Math.round(10 * j / (xs.length - 1)) / 10 : null;
  };

  function summarizePing(rtts) {
    return { ping_ms: rtts.length ? Math.round(median(rtts)) : null, jitter_ms: meanStep(rtts) };
  }

  // sent: packets sent; echoes: [{seq, rtt, at}] in arrival order (ms). Duplicates are dropped.
  // A gap is time between consecutive echoes > 250 ms: at 100 packets/s that is ~25 lost in a row,
  // the shape of a game-visible stall rather than scattered loss.
  function summarizeStall(sent, echoes, seconds) {
    const seen = new Set(), uniq = [];
    for (const e of echoes) if (!seen.has(e.seq)) { seen.add(e.seq); uniq.push(e); }
    const rtts = uniq.map((e) => e.rtt);
    let gaps = 0, worst = 0;
    for (let i = 1; i < uniq.length; i++) {
      const g = uniq[i].at - uniq[i - 1].at;
      if (g > GAP_MS) gaps++;
      if (g > worst) worst = g;
    }
    return {
      stall_seconds: seconds,
      stall_sent: sent,
      stall_loss_pct: sent ? Math.round(1000 * (sent - uniq.length) / sent) / 10 : null,
      stall_rtt_ms: rtts.length ? Math.round(median(rtts)) : null,
      stall_jitter_ms: meanStep(rtts),
      stall_gaps_250: gaps,
      stall_worst_gap_ms: Math.round(worst),
    };
  }

  class Busy extends Error {}

  async function call(o, method, p, body) {
    const sep = p.includes('?') ? '&' : '?';
    const r = await o.fetch(`${o.base}${p}${sep}t=${encodeURIComponent(o.ticket)}`, { method, body, cache: 'no-store', signal: o.signal });
    if (r.status === 409) throw new Busy('match in progress');
    if (!r.ok && r.status !== 204) throw new Error(`${p}: ${r.status} ${(await r.text()).slice(0, 200)}`);
    return r;
  }

  async function ping(o, n = 20) {
    const rtts = [];
    for (let i = 0; i < n; i++) {
      const t0 = o.now();
      await call(o, 'GET', '/ping');
      rtts.push(o.now() - t0);
    }
    return summarizePing(rtts.slice(1));  // first request pays connection setup
  }

  // Streamed until `mb` arrive or `seconds` pass, whichever first.
  async function download(o, mb = 25, seconds = 8) {
    const ctl = new AbortController();
    const t0 = o.now();
    const timer = setTimeout(() => ctl.abort(), seconds * 1000);
    let n = 0;
    try {
      const r = await call({ ...o, signal: ctl.signal }, 'GET', `/down?mb=${mb}`);
      const rd = r.body.getReader();
      for (;;) { const { done, value } = await rd.read(); if (done) break; n += value.length; }
    } catch (e) { if (e instanceof Busy) throw e; if (!ctl.signal.aborted) throw e; }
    finally { clearTimeout(timer); }
    return Math.round(10 * (n * 8 / 1e6) / ((o.now() - t0) / 1000)) / 10;
  }

  // 1 MB posts back to back until `mb` sent or `seconds` pass.
  async function upload(o, mb = 25, seconds = 8) {
    const chunk = new Uint8Array(1024 * 1024);
    for (let i = 0; i < chunk.length; i += 65536) (root.crypto || require('node:crypto').webcrypto).getRandomValues(chunk.subarray(i, i + 65536));
    const t0 = o.now();
    let n = 0;
    while (n < mb && o.now() - t0 < seconds * 1000) { await call(o, 'POST', '/up', chunk); n++; }
    return Math.round(10 * (n * 8.388608) / ((o.now() - t0) / 1000)) / 10;
  }

  // 100 packets/s of [seq u32][sent f64] over an unordered, no-retransmit data channel.
  async function stall(o, seconds = 60, rate = 100) {
    const pc = new o.RTCPeerConnection();
    const dc = pc.createDataChannel('stall', { ordered: false, maxRetransmits: 0 });
    dc.binaryType = 'arraybuffer';
    const echoes = [];
    dc.onmessage = (ev) => {
      const at = o.now();
      const v = new DataView(ev.data instanceof ArrayBuffer ? ev.data : ev.data.buffer.slice(ev.data.byteOffset, ev.data.byteOffset + ev.data.byteLength));
      echoes.push({ seq: v.getUint32(0), rtt: at - v.getFloat64(4), at });
    };
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise((ok) => {
        if (pc.iceGatheringState === 'complete') return ok();
        pc.addEventListener('icegatheringstatechange', () => pc.iceGatheringState === 'complete' && ok());
        setTimeout(ok, 3000);
      });
      const r = await call(o, 'POST', '/stall/offer', pc.localDescription.sdp);
      await pc.setRemoteDescription({ type: 'answer', sdp: (await r.json()).sdp });
      await new Promise((ok, no) => {
        if (dc.readyState === 'open') return ok();
        dc.onopen = ok;
        setTimeout(() => no(new Error('stall channel did not open (UDP blocked?)')), 10000);
      });
      let sent = 0;
      const total = seconds * rate;
      await new Promise((ok) => {
        const t0 = o.now();
        const tick = () => {
          // Catch up on timer slop so the packet count, not the timer, sets the pace.
          const due = Math.min(total, Math.floor((o.now() - t0) * rate / 1000));
          for (; sent < due; sent++) {
            const b = new ArrayBuffer(12), v = new DataView(b);
            v.setUint32(0, sent); v.setFloat64(4, o.now());
            try { dc.send(b); } catch { /* counted as lost */ }
          }
          if (o.onProgress) o.onProgress({ phase: 'stall', done: sent / total });
          if (sent >= total) return setTimeout(ok, 1000);  // let the last echoes land
          setTimeout(tick, 10);
        };
        tick();
      });
      return summarizeStall(sent, echoes, seconds);
    } finally { try { dc.close(); } catch { /* */ } pc.close(); }
  }

  // Stall first (it answers the complaint), then ping, then bandwidth. If the region goes busy
  // after the stall test, the rest is skipped and the row says so (`busy_skipped`).
  async function runTest(opts) {
    const o = {
      fetch: root.fetch && root.fetch.bind(root),
      RTCPeerConnection: root.RTCPeerConnection,
      now: () => (root.performance || Date).now(),
      stallSeconds: 60, mb: 25,
      ...opts,
      base: String(opts.base).replace(/\/$/, ''),
    };
    const out = { client_version: VERSION, busy_skipped: false };
    const step = (phase) => o.onProgress && o.onProgress({ phase, done: 0 });
    step('stall');
    Object.assign(out, await stall(o, o.stallSeconds));
    try {
      step('ping'); Object.assign(out, await ping(o));
      step('download'); out.down_mbps = await download(o, o.mb);
      step('upload'); out.up_mbps = await upload(o, o.mb);
    } catch (e) {
      if (!(e instanceof Busy)) throw e;
      out.busy_skipped = true;
    }
    step('done');
    return out;
  }

  const api = { runTest, summarizeStall, summarizePing, Busy, GAP_MS, VERSION };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KtpNettest = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
