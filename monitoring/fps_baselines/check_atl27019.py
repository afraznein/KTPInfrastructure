#!/usr/bin/env python3
"""Pull the FPS time series from atlanta:27019 to see whether the
post-JIT σ regression is a transient (e.g. startup/match boundary)
or a sustained anomaly."""
import io, sys, re, datetime
import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

FPS_RE = re.compile(r'L (\d{2}/\d{2}/\d{4}) - (\d{2}:\d{2}:\d{2}):\s*\[KTP_PROFILE\][^\n]*frames=(\d+)\s+fps=([\d.]+)')

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('74.91.121.9', username='dodserver', password='ktp', timeout=15,
          allow_agent=False, look_for_keys=False)
_, out, _ = c.exec_command(
    'grep "\\[KTP_PROFILE\\]" ~/dod-27019/log/console/*-console.log 2>/dev/null',
    timeout=60)
data = out.read().decode('utf-8', errors='replace')
c.close()

samples = []
for line in data.splitlines():
    m = FPS_RE.search(line)
    if m:
        try:
            ts = datetime.datetime.strptime(f'{m.group(1)} {m.group(2)}', '%m/%d/%Y %H:%M:%S')
            samples.append((ts, float(m.group(4))))
        except ValueError:
            pass
samples.sort()

print(f'Total samples: {len(samples)}')
if samples:
    print(f'First: {samples[0][0]} fps={samples[0][1]}')
    print(f'Last : {samples[-1][0]} fps={samples[-1][1]}')

# Bucket per-hour stats
buckets = {}
for ts, v in samples:
    key = ts.strftime('%Y-%m-%d %H:00')
    buckets.setdefault(key, []).append(v)

import statistics
print()
print(f'  hour                  n     min     p50     mean    σ      max')
for h in sorted(buckets):
    v = buckets[h]
    if len(v) < 5:
        continue
    s = sorted(v)
    p50 = s[len(s)//2]
    print(f'  {h}  {len(v):>4}  {min(v):>6.1f} {p50:>7.1f} {statistics.fmean(v):>7.2f} '
          f'{statistics.pstdev(v):>5.2f}  {max(v):>6.1f}')

# Spike (≥10 fps below p50) clustering
all_p50 = statistics.median([v for _, v in samples])
threshold = all_p50 - 10
spikes = [(ts, v) for ts, v in samples if v < threshold]
print()
print(f'Samples <p50-10 ({threshold:.1f}): {len(spikes)} ({100*len(spikes)/len(samples):.2f}%)')
if spikes:
    print('  First 10 low-fps events:')
    for ts, v in spikes[:10]:
        print(f'    {ts}  fps={v:.1f}')
    print('  Last 10 low-fps events:')
    for ts, v in spikes[-10:]:
        print(f'    {ts}  fps={v:.1f}')
