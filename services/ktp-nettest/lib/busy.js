'use strict';
// Is any match live on this host? Read from the host's own game logs, so the block needs neither
// the website nor the data server: an instance is live from its last KTP_MATCH_START until a later
// KTP_MATCH_END, or for at most MAX_LIVE_S after the start (a crashed match must not block forever).
// Same markers the profile aggregator uses for match attribution.
const fs = require('node:fs');
const path = require('node:path');

const MAX_LIVE_S = 2 * 3600;
const TAIL_BYTES = 2 * 1024 * 1024;
const TS = /^L (\d{2})\/(\d{2})\/(\d{4}) - (\d{2}):(\d{2}):(\d{2}):/;

function lineTime(line) {
  const m = TS.exec(line);
  if (!m) return null;
  // Log time is the host's local clock; compared only against Date.now() on the same host.
  return new Date(+m[3], +m[1] - 1, +m[2], +m[4], +m[5], +m[6]).getTime() / 1000;
}

// Pure: given a log tail, is the last match still live at `now` (epoch s)?
function liveInText(text, now) {
  let start = null, end = null;
  for (const line of text.split('\n')) {
    if (line.includes('KTP_MATCH_START')) { start = lineTime(line); end = null; }
    else if (line.includes('KTP_MATCH_END') && start !== null) end = lineTime(line);
  }
  return start !== null && end === null && now - start < MAX_LIVE_S;
}

// The two newest logs: halves are separate maps, so between halves (and during second-half
// warmup) the newest log has no START yet while the first half's START, unended, sits in the
// previous one.
function newestLogs(dir) {
  return fs.readdirSync(dir)
    .filter((f) => /^L.*\.log$/.test(f))
    .map((f) => ({ file: path.join(dir, f), mtime: fs.statSync(path.join(dir, f)).mtimeMs }))
    .sort((a, b) => a.mtime - b.mtime)
    .slice(-2)
    .map((x) => x.file);
}

function tail(file) {
  const st = fs.statSync(file);
  const fd = fs.openSync(file, 'r');
  try {
    const len = Math.min(st.size, TAIL_BYTES);
    const buf = Buffer.alloc(len);
    fs.readSync(fd, buf, 0, len, st.size - len);
    return buf.toString('utf8');
  } finally { fs.closeSync(fd); }
}

// dirs: each game instance's dod/logs directory (e.g. ~/dod-27015/serverfiles/dod/logs) on this host. Cached for `ttlS`. Unreadable logs
// count as BUSY: when in doubt, do not load a box that may be hosting a match.
function makeBusy(dirs, { ttlS = 15 } = {}) {
  let cache = { at: 0, busy: true };
  return function isBusy(now = Date.now() / 1000) {
    if (now - cache.at < ttlS) return cache.busy;
    let busy = false;
    try {
      for (const d of dirs) {
        if (liveInText(newestLogs(d).map(tail).join('\n'), now)) { busy = true; break; }
      }
    } catch { busy = true; }
    cache = { at: now, busy: dirs.length ? busy : true };
    return cache.busy;
  };
}

module.exports = { liveInText, makeBusy, MAX_LIVE_S };
