'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { mint, verify } = require('../lib/ticket');
const { liveInText, makeBusy } = require('../lib/busy');
const { summarizeStall, summarizePing } = require('../client');

const S = 'test-secret';
const NOW = 1_800_000_000;
const tk = (o = {}) => mint(S, { jti: 'a', pid: 7, region: 'NY', exp: NOW + 300, ...o });

test('ticket: good ticket verifies', () => {
  const v = verify(S, tk(), { region: 'NY', now: NOW });
  assert.ok(v.ok);
  assert.strictEqual(v.t.pid, 7);
});

test('ticket: rejects missing, forged, expired, wrong region, no secret', () => {
  assert.strictEqual(verify(S, undefined, { region: 'NY', now: NOW }).why, 'missing ticket');
  assert.strictEqual(verify('other', tk(), { region: 'NY', now: NOW }).why, 'bad signature');
  const [body, sig] = tk().split('.');
  const forged = Buffer.from(JSON.stringify({ jti: 'a', pid: 8, region: 'NY', exp: NOW + 300 })).toString('base64url');
  assert.strictEqual(verify(S, `${forged}.${sig}`, { region: 'NY', now: NOW }).why, 'bad signature');
  assert.strictEqual(verify(S, `${body}.`, { region: 'NY', now: NOW }).why, 'bad signature');
  assert.strictEqual(verify(S, tk({ exp: NOW }), { region: 'NY', now: NOW }).why, 'expired ticket');
  assert.strictEqual(verify(S, tk(), { region: 'CHI', now: NOW }).why, 'ticket is for another region');
  assert.strictEqual(verify('', tk(), { region: 'NY', now: NOW }).ok, false);
});

test('ticket: one run per player per 10 minutes, same ticket reusable within its run', () => {
  const spent = new Map();
  assert.ok(verify(S, tk(), { region: 'NY', now: NOW, spent }).ok);
  assert.ok(verify(S, tk(), { region: 'NY', now: NOW + 60, spent }).ok, 'same ticket, later request in the run');
  const second = verify(S, tk({ jti: 'b' }), { region: 'NY', now: NOW + 120, spent });
  assert.strictEqual(second.status, 429);
  assert.ok(verify(S, tk({ jti: 'c', pid: 9 }), { region: 'NY', now: NOW + 120, spent }).ok, 'other player unaffected');
  assert.ok(verify(S, tk({ jti: 'd', exp: NOW + 900 }), { region: 'NY', now: NOW + 601, spent }).ok, 'after cooldown');
});

const L = (d, msg) => {
  const p = (n) => String(n).padStart(2, '0');
  return `L ${p(d.getMonth() + 1)}/${p(d.getDate())}/${d.getFullYear()} - ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}: ${msg}`;
};

test('busy: live from KTP_MATCH_START until KTP_MATCH_END or 2 h', () => {
  const t0 = new Date(2026, 9, 25, 20, 0, 0);
  const now = t0.getTime() / 1000;
  const start = L(t0, '"KTP_MATCH_START" (matchid "1.3-1-NY1")');
  const end = L(new Date(t0.getTime() + 1800e3), '"KTP_MATCH_END" (matchid "1.3-1-NY1")');
  assert.strictEqual(liveInText('', now), false);
  assert.strictEqual(liveInText(start, now + 60), true);
  assert.strictEqual(liveInText(`${start}\n${end}`, now + 1900), false);
  assert.strictEqual(liveInText(start, now + 2 * 3600 + 1), false, 'crashed match stops blocking');
  const restart = L(new Date(t0.getTime() + 2000e3), '"KTP_MATCH_START" (matchid "1.3-2-NY1")');
  assert.strictEqual(liveInText(`${start}\n${end}\n${restart}`, now + 2100), true, 'second match on same log');
});

test('busy: newest log per dir, unreadable or unconfigured counts as busy', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nettest-'));
  const t0 = new Date();
  fs.writeFileSync(path.join(dir, 'L1025000.log'), L(t0, '"KTP_MATCH_START"') + '\n');
  const old = path.join(dir, 'L1024000.log');
  fs.writeFileSync(old, '');
  fs.utimesSync(old, new Date(0), new Date(0));
  assert.strictEqual(makeBusy([dir])(), true);
  fs.appendFileSync(path.join(dir, 'L1025000.log'), L(t0, '"KTP_MATCH_END"') + '\n');
  assert.strictEqual(makeBusy([dir])(), false);
  assert.strictEqual(makeBusy([path.join(dir, 'nope')])(), true);
  assert.strictEqual(makeBusy([])(), true);
  fs.rmSync(dir, { recursive: true });
});

test('stall summary: loss, gaps over 250 ms, duplicates ignored', () => {
  const echoes = [];
  for (let i = 0; i < 100; i++) {
    if (i >= 40 && i < 80) continue;  // 400 ms hole
    echoes.push({ seq: i, rtt: 30 + (i % 2) * 4, at: i * 10 });
  }
  echoes.push({ seq: 5, rtt: 99, at: 999 });
  const s = summarizeStall(100, echoes, 1);
  assert.strictEqual(s.stall_loss_pct, 40);
  assert.strictEqual(s.stall_gaps_250, 1);
  assert.strictEqual(s.stall_worst_gap_ms, 410);
  assert.strictEqual(s.stall_rtt_ms, 32);
  assert.strictEqual(s.stall_jitter_ms, 4);
  assert.deepStrictEqual(summarizePing([]), { ping_ms: null, jitter_ms: null });
  assert.deepStrictEqual(summarizePing([20, 30, 20]), { ping_ms: 20, jitter_ms: 10 });
});

test('busy: first half START in previous log keeps the box busy through the map change', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nettest-'));
  const t0 = new Date();
  const h1 = path.join(dir, 'L1025000.log');
  fs.writeFileSync(h1, L(t0, '"KTP_MATCH_START"') + '\n');
  fs.utimesSync(h1, new Date(Date.now() - 60e3), new Date(Date.now() - 60e3));
  fs.writeFileSync(path.join(dir, 'L1025001.log'), L(t0, 'Loading map "dod_anzio"') + '\n');
  assert.strictEqual(makeBusy([dir])(), true);
  fs.rmSync(dir, { recursive: true });
});
