'use strict';
// Run tickets: the website mints one for a signed-in player; the node runs nothing without it.
// Format: base64url(JSON {jti, pid, region, exp}) + "." + base64url(HMAC-SHA256(secret, part1)).
// exp is epoch seconds. Shared secret: KTP_NETTEST_TICKET_SECRET (site env + node unit env).
const crypto = require('node:crypto');

const b64u = (buf) => Buffer.from(buf).toString('base64url');

function mint(secret, { jti, pid, region, exp }) {
  const body = b64u(JSON.stringify({ jti, pid, region, exp }));
  const sig = b64u(crypto.createHmac('sha256', secret).update(body).digest());
  return `${body}.${sig}`;
}

// Returns {ok:true, t} or {ok:false, why}. `spent` maps pid -> {jti, at}: one run per player per
// `cooldownS`; the same ticket may make many requests (ping x20, transfer, stall) until it expires.
function verify(secret, ticket, { region, now = Date.now() / 1000, spent, cooldownS = 600 }) {
  if (!secret) return { ok: false, why: 'node has no ticket secret' };
  if (typeof ticket !== 'string' || !ticket.includes('.')) return { ok: false, why: 'missing ticket' };
  const [body, sig] = ticket.split('.', 2);
  const want = crypto.createHmac('sha256', secret).update(body).digest();
  let got;
  try { got = Buffer.from(sig, 'base64url'); } catch { return { ok: false, why: 'bad signature' }; }
  if (got.length !== want.length || !crypto.timingSafeEqual(got, want)) return { ok: false, why: 'bad signature' };
  let t;
  try { t = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')); } catch { return { ok: false, why: 'bad ticket' }; }
  if (!t || !t.jti || !t.pid || typeof t.exp !== 'number') return { ok: false, why: 'bad ticket' };
  if (t.exp <= now) return { ok: false, why: 'expired ticket' };
  if (t.region !== region) return { ok: false, why: 'ticket is for another region' };
  if (spent) {
    const prev = spent.get(String(t.pid));
    if (prev && prev.jti !== t.jti && now - prev.at < cooldownS) return { ok: false, why: 'one run per 10 minutes', status: 429 };
    if (!prev || prev.jti !== t.jti) spent.set(String(t.pid), { jti: t.jti, at: now });
  }
  return { ok: true, t };
}

module.exports = { mint, verify };
