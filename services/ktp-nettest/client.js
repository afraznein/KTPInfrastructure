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
  const VERSION = 'ktp-nettest-client/2';

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

  // echoes: [{seq, rtt, at}] in arrival order; sendAt[seq]: when each packet left. A gap over 250 ms
  // is charged to the line only for the part the sender was not itself paused, or a throttled
  // browser's bursts read as stalls.
  function summarizeStall(sent, echoes, seconds, sendAt = []) {
    const seen = new Set(), uniq = [];
    for (const e of echoes) if (!seen.has(e.seq)) { seen.add(e.seq); uniq.push(e); }
    const rtts = uniq.map((e) => e.rtt);
    const pause = (k) => (k > 0 && sendAt[k] != null && sendAt[k - 1] != null ? sendAt[k] - sendAt[k - 1] : 0);
    let sendGaps = 0, sendWorst = 0;
    for (let k = 1; k < sendAt.length; k++) {
      const p = pause(k);
      if (p > GAP_MS) sendGaps++;
      if (p > sendWorst) sendWorst = p;
    }
    let gaps = 0, worst = 0, recvGaps = 0, recvWorst = 0;
    for (let i = 1; i < uniq.length; i++) {
      const g = uniq[i].at - uniq[i - 1].at;
      if (g > GAP_MS) recvGaps++;
      if (g > recvWorst) recvWorst = g;
      const lo = Math.min(uniq[i].seq, uniq[i - 1].seq), hi = Math.max(uniq[i].seq, uniq[i - 1].seq);
      let held = 0;
      for (let k = lo + 1; k <= hi; k++) held = Math.max(held, pause(k));
      const line = g - held;
      if (line > GAP_MS) gaps++;
      if (line > worst) worst = line;
    }
    return {
      stall_seconds: seconds,
      stall_sent: sent,
      stall_loss_pct: sent ? Math.round(1000 * (sent - uniq.length) / sent) / 10 : null,
      stall_rtt_ms: rtts.length ? Math.round(median(rtts)) : null,
      stall_jitter_ms: meanStep(rtts),
      stall_gaps_250: gaps,
      stall_worst_gap_ms: Math.round(worst),
      stall_recv_gaps_250: recvGaps,
      stall_recv_worst_gap_ms: Math.round(recvWorst),
      stall_send_gaps_250: sendGaps,
      stall_send_worst_gap_ms: Math.round(sendWorst),
    };
  }

  // Chrome clamps page timers to 1 Hz in a hidden tab and in a display:none cross-origin frame (how
  // the site embeds /frame); a worker's timer is not, so it drives sending, the page timer backs it up.
  function defaultClock(o) {
    return (onTick) => {
      let live = true, t = null, w = null;
      if (o.Worker) {
        try { w = new o.Worker(`${o.base}/tick.js`); w.onmessage = () => live && onTick(); w.onerror = () => {}; } catch { w = null; }
      }
      const loop = () => { if (!live) return; onTick(); t = setTimeout(loop, 10); };
      t = setTimeout(loop, 10);
      return () => { live = false; clearTimeout(t); if (w) w.terminate(); };
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
      let sent = 0, stop = () => {};
      const total = seconds * rate, sendAt = [];
      try {
        await new Promise((ok) => {
          const t0 = o.now();
          let finished = false;
          const tick = () => {
            if (finished) return;
            // Catch up on timer slop so the packet count, not the timer, sets the pace.
            const due = Math.min(total, Math.floor((o.now() - t0) * rate / 1000));
            for (; sent < due; sent++) {
              const b = new ArrayBuffer(12), v = new DataView(b), at = o.now();
              v.setUint32(0, sent); v.setFloat64(4, at);
              sendAt.push(at);
              try { dc.send(b); } catch { /* counted as lost */ }
            }
            if (o.onProgress) o.onProgress({ phase: 'stall', done: sent / total });
            if (sent >= total) { finished = true; stop(); setTimeout(ok, 1000); }  // let the last echoes land
          };
          stop = (o.clock || defaultClock(o))(tick);
          tick();
        });
      } finally { stop(); }
      return summarizeStall(sent, echoes, seconds, sendAt);
    } finally { try { dc.close(); } catch { /* */ } pc.close(); }
  }

  // Stall first (it answers the complaint), then ping, then bandwidth. If the region goes busy
  // after the stall test, the rest is skipped and the row says so (`busy_skipped`).
  async function runTest(opts) {
    const o = {
      fetch: root.fetch && root.fetch.bind(root),
      RTCPeerConnection: root.RTCPeerConnection,
      Worker: root.Worker,
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
