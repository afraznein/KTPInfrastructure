/**
 * node --test
 *
 * Layer 1: hand-built unit vectors. Expected values were computed independently
 *          in Python (`1/(1+math.exp(-x))`) and pasted as literals, so this is
 *          not the implementation checking itself. Tolerance 1e-9.
 * Layer 2: golden curve. golden.json is produced by make_golden.py driving the
 *          real pipeline's `_HalfState.p_allies`; we replay the same event
 *          stream here. Tolerance 1e-6.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { FlagSwing } from './flagswing.js';

const close = (actual, expected, tol, message) =>
  assert.ok(
    Math.abs(actual - expected) <= tol,
    `${message}: got ${actual}, want ${expected} (|d|=${Math.abs(actual - expected)} > ${tol})`,
  );

/** 6v6 roster, ids 1..6 allies, 11..16 axis. */
const sixVsSix = (options) => {
  const fs = new FlagSwing(options);
  for (let i = 1; i <= 6; i += 1) fs.setTeam(i, 1);
  for (let i = 11; i <= 16; i += 1) fs.setTeam(i, 2);
  return fs;
};

test('even flags and even players is exactly 0.5', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  close(fs.pAllies(), 0.5, 1e-9, 'even');
});

test('no flags owned at all: only the alive term moves it', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  fs.setAlive(16, false); // 6 allies vs 5 axis
  close(fs.pAllies(), 0.520821285372743, 1e-9, 'one man up, no flags');
});

test('all five flags to the allies', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  for (let f = 0; f < 5; f += 1) fs.setFlagOwner(f, 1);
  close(fs.pAllies(), 0.8807970779778823, 1e-9, 'sigmoid(2)');
});

test('all five flags to the axis', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  for (let f = 0; f < 5; f += 1) fs.setFlagOwner(f, 2);
  close(fs.pAllies(), 0.11920292202211755, 1e-9, 'sigmoid(-2)');
});

test('neutral flags (owner not 1 or 2) count for neither side', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  fs.setFlagOwner(0, 0);
  fs.setFlagOwner(1, null);
  fs.setFlagOwner(2, 3);
  close(fs.pAllies(), 0.5, 1e-9, 'neutral flags');
});

test('one team wiped: 6 allies alive vs 0 axis, roster denominator is 12', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  for (let i = 11; i <= 16; i += 1) fs.setAlive(i, false);
  close(fs.pAllies(), 0.6224593312018546, 1e-9, 'sigmoid(6/12)');
});

test('roster size is BOTH teams combined, not per team', () => {
  const combined = sixVsSix({ flagCount: 5, rosterSize: 12 });
  const perTeam = sixVsSix({ flagCount: 5, rosterSize: 6 });
  combined.setAlive(16, false);
  perTeam.setAlive(16, false);
  close(combined.pAllies(), 0.520821285372743, 1e-9, 'roster 12');
  close(perTeam.pAllies(), 0.5416, 1e-4, 'roster 6 differs, i.e. the split matters');
  assert.notEqual(combined.pAllies(), perTeam.pAllies());
});

test('rosterSize defaults to the number of known players', () => {
  const fs = sixVsSix({ flagCount: 5 });
  assert.equal(fs.rosterDenominator, 12);
  fs.setAlive(16, false);
  close(fs.pAllies(), 0.520821285372743, 1e-9, 'derived roster 12');
});

test('empty roster: alive term is 0 and the denominator floors at 1', () => {
  const fs = new FlagSwing({ flagCount: 5, rosterSize: 0 });
  assert.equal(fs.rosterDenominator, 1);
  close(fs.pAllies(), 0.5, 1e-9, 'empty roster, no flags');
  fs.setFlagOwner(0, 1);
  close(fs.pAllies(), 0.598687660112452, 1e-9, 'empty roster, one allied flag of 5');
});

test('roster denominator floor of 1 with a single player', () => {
  const fs = new FlagSwing({ flagCount: 5, rosterSize: 0 });
  fs.setTeam(7, 1);
  close(fs.pAllies(), 0.7310585786300049, 1e-9, 'sigmoid(1/1)');
});

test('flagCount falls back to 5 when absent or zero', () => {
  for (const options of [{ rosterSize: 12 }, { flagCount: 0, rosterSize: 12 }, { flagCount: null, rosterSize: 12 }]) {
    const fs = sixVsSix(options);
    assert.equal(fs.flagDenominator, 5);
    fs.setFlagOwner(null, 1); // flag with no index: numerator only, per the pipeline
    close(fs.pAllies(), 0.598687660112452, 1e-9, `fallback 5 for ${JSON.stringify(options)}`);
  }
});

test('flag denominator floors at 1', () => {
  const fs = sixVsSix({ flagCount: 1, rosterSize: 12 });
  fs.setFlagOwner(0, 1);
  close(fs.pAllies(), 0.8807970779778823, 1e-9, 'sigmoid(2*1/1)');
});

test('flag count is the number of DISTINCT indices, not of ownership changes', () => {
  const fs = sixVsSix({ flagCount: 3, rosterSize: 12 });
  fs.setFlagOwner(0, 2);
  fs.setFlagOwner(0, 1); // same flag re-capped, not a second flag
  fs.setFlagOwner(1, 1);
  fs.setFlagOwner(2, 2);
  close(fs.pAllies(), 0.6607563687658172, 1e-9, 'sigmoid(2*(1/3))');
});

test('team 1 is allies and team 2 is axis', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  fs.setFlagOwner(0, 1);
  fs.setFlagOwner(1, 1);
  fs.setFlagOwner(2, 2);
  fs.setFlagOwner(3, 2);
  fs.setFlagOwner(4, 1);
  for (let i = 14; i <= 16; i += 1) fs.setAlive(i, false);
  close(fs.pAllies(), 0.6570104626734988, 1e-9, 'sigmoid(2*(1/5)+3/12)');
});

test('mixed flags and frags, axis ahead', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  fs.setFlagOwner(0, 2);
  close(fs.pAllies(), 0.401312339887548, 1e-9, 'sigmoid(-0.4)');
});

test('unknown players are ignored by setAlive', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  fs.setAlive(999, false);
  close(fs.pAllies(), 0.5, 1e-9, 'spectator frag does not move the curve');
});

test('resetHalf clears flag ownership and revives everyone', () => {
  const fs = sixVsSix({ flagCount: 5, rosterSize: 12 });
  for (let f = 0; f < 5; f += 1) fs.setFlagOwner(f, 2);
  for (let i = 1; i <= 6; i += 1) fs.setAlive(i, false);
  assert.ok(fs.pAllies() < 0.1);
  fs.resetHalf();
  assert.equal(fs.owners.size, 0);
  close(fs.pAllies(), 0.5, 1e-9, 'half boundary is a full reset');
});

test('coefficients are configurable and must be non-negative', () => {
  const fs = sixVsSix({ flagCoefficient: 0, aliveCoefficient: 1, flagCount: 5, rosterSize: 12 });
  for (let f = 0; f < 5; f += 1) fs.setFlagOwner(f, 1);
  close(fs.pAllies(), 0.5, 1e-9, 'zeroed flag coefficient');
  assert.throws(() => new FlagSwing({ flagCoefficient: -1 }), RangeError);
  assert.throws(() => new FlagSwing({ aliveCoefficient: -1 }), RangeError);
});

// ---------------------------------------------------------------- golden curve

const golden = JSON.parse(
  readFileSync(new URL('./golden.json', import.meta.url), 'utf-8'),
);

test('golden.json is the flag_swing_v1 definition', () => {
  assert.equal(golden.definition, 'flag_swing_v1');
  assert.equal(golden.definition_version, 1);
  assert.equal(golden.cases.length, 3);
});

for (const kase of golden.cases) {
  test(`golden curve: ${kase.match_id} (${kase.steps.length} steps)`, () => {
    const fs = new FlagSwing({
      flagCoefficient: kase.flagCoefficient,
      aliveCoefficient: kase.aliveCoefficient,
      flagCount: kase.flagCount,
      rosterSize: kase.rosterSize,
    });
    for (const [pid, team] of kase.teams) fs.setTeam(pid, team);
    let maxError = 0;
    kase.steps.forEach((step, index) => {
      if (step.op === 'resetHalf') fs.resetHalf();
      else if (step.op === 'flag') fs.setFlagOwner(step.flag, step.owner);
      else if (step.op === 'alive') fs.setAlive(step.player, step.up);
      else assert.fail(`unknown op ${step.op}`);
      const actual = fs.pAllies();
      maxError = Math.max(maxError, Math.abs(actual - step.p));
      close(actual, step.p, 1e-6, `${kase.match_id} step ${index} (${step.op})`);
    });
    assert.ok(kase.steps.length > 100, 'golden case should be a real curve');
    assert.ok(maxError < 1e-6, `max error ${maxError}`);
  });
}
