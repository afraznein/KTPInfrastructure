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

test('busy: a tail truncated past its START cannot report not-live', () => {
  const t0 = new Date(2026, 9, 25, 20, 0, 0);
  const now = t0.getTime() / 1000;
  const start = L(t0, '"KTP_MATCH_START" (matchid "1.3-1-NY1")');
  const end = L(new Date(t0.getTime() + 1800e3), '"KTP_MATCH_END" (matchid "1.3-1-NY1")');
  // What the window actually held mid-half once the log outgrew it: the START scrolled out.
  const midHalf = L(t0, 'World triggered "Round_Win"');

  assert.strictEqual(liveInText(midHalf, now + 60, true), true, 'truncated, no START: cannot tell');
  // The control that makes the line above a test and not a constant. 92% of this fleet's logs
  // carry no START at all, so a marker-free COMPLETE read has to stay not-busy -- otherwise the
  // node reports busy on an idle host and never serves a test.
  assert.strictEqual(liveInText(midHalf, now + 60, false), false, 'complete, no START: idle');
  // A truncated read is not trustworthy even when what it did see looks finished: the START it
  // missed could be anywhere in the part it never read.
  assert.strictEqual(liveInText(`${start}\n${end}`, now + 1900, true), true);
  assert.strictEqual(liveInText(`${start}\n${end}`, now + 1900, false), false);
});

test('busy: an idle host whose newest logs carry no marker is not busy', () => {
  // Measured 2026-10-28 on newyork 27015: 2998 of 3261 logs contain no KTP_MATCH_START, and the
  // two newest had none. Treating that as busy would make the node permanently unavailable.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nettest-'));
  const t0 = new Date();
  fs.writeFileSync(path.join(dir, 'L1028069.log'), L(t0, 'Loading map "dod_donner"') + '\n');
  fs.writeFileSync(path.join(dir, 'L1028070.log'), L(t0, 'Started map "dod_donner"') + '\n');
  assert.strictEqual(makeBusy([dir])(), false);
  fs.rmSync(dir, { recursive: true });
});

test('busy: a half whose log outgrew the window still blocks', () => {
  // The bug as it occurred: a START at the top of a half, then more log than the window holds
  // and no END yet. This is the only case here that exercises the real file read, so it is the
  // one that would have caught the 2 MB window.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nettest-'));
  const t0 = new Date();
  const f = path.join(dir, 'L1028100.log');
  fs.writeFileSync(f, L(t0, '"KTP_MATCH_START"') + '\n');
  const filler = (L(t0, 'World triggered "Round_Win"') + '\n').repeat(4096);
  for (let i = 0; i < 110; i++) fs.appendFileSync(f, filler);
  assert.ok(fs.statSync(f).size > 16 * 1024 * 1024, 'fixture must exceed the window to mean anything');
  assert.strictEqual(makeBusy([dir])(), true);
  fs.rmSync(dir, { recursive: true });
});
