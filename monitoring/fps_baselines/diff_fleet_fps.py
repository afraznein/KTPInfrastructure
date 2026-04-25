#!/usr/bin/env python3
"""Diff two fleet_fps_*.json snapshots — print fleet, per-host, and
per-instance deltas with focus on JIT A/B comparison metrics."""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _delta(post, pre, fmt='{:+.2f}'):
    if post is None or pre is None:
        return 'n/a'
    return fmt.format(post - pre)


def fmt_block(label: str, pre: dict, post: dict, indent: int = 0) -> str:
    pad = ' ' * indent
    lines = [f'{pad}{label}']
    rows = [
        ('n',     '{:>9d}', '{:>9d}',  None),
        ('p50',   '{:>9.1f}', '{:>9.1f}', '{:+.1f}'),
        ('p99',   '{:>9.1f}', '{:>9.1f}', '{:+.1f}'),
        ('mean',  '{:>9.2f}', '{:>9.2f}', '{:+.2f}'),
        ('stdev', '{:>9.2f}', '{:>9.2f}', '{:+.2f}'),
        ('min',   '{:>9.1f}', '{:>9.1f}', '{:+.1f}'),
        ('max',   '{:>9.1f}', '{:>9.1f}', '{:+.1f}'),
        ('pct_in_nfo_window', '{:>9.4f}', '{:>9.4f}', '{:+.4f}'),
        ('pct_within_10',     '{:>9.4f}', '{:>9.4f}', '{:+.4f}'),
    ]
    lines.append(f'{pad}  {"":<20} {"pre":>9}  {"post":>9}   delta')
    for key, fmt_pre, fmt_post, fmt_d in rows:
        a = pre.get(key)
        b = post.get(key)
        sa = fmt_pre.format(a) if a is not None else '      n/a'
        sb = fmt_post.format(b) if b is not None else '      n/a'
        sd = ('  ' + _delta(b, a, fmt_d)) if fmt_d else ''
        lines.append(f'{pad}  {key:<20} {sa}  {sb} {sd}')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('pre',  type=Path)
    ap.add_argument('post', type=Path)
    args = ap.parse_args()

    pre = json.loads(args.pre.read_text(encoding='utf-8'))
    post = json.loads(args.post.read_text(encoding='utf-8'))

    print(f'PRE : {args.pre.name}  label={pre.get("label")}  captured={pre.get("captured_at_utc")}')
    print(f'POST: {args.post.name}  label={post.get("label")}  captured={post.get("captured_at_utc")}')
    print()

    print(fmt_block('Fleet', pre['fleet_stats'], post['fleet_stats']))
    print()

    print('Per host:')
    for host in pre['per_host_stats']:
        if host in post['per_host_stats']:
            print()
            print(fmt_block(host, pre['per_host_stats'][host],
                            post['per_host_stats'][host], indent=2))
    print()

    # Per-instance: compact one-line summary, flag biggest outliers
    print('Per-instance (sorted by stdev change desc):')
    print(f'  {"instance":<22} {"n_pre":>7} {"n_post":>7}  '
          f'{"p50_pre":>8} {"p50_post":>8} {"Δp50":>7}  '
          f'{"σ_pre":>7} {"σ_post":>7} {"Δσ":>7}  '
          f'{"min_pre":>7} {"min_post":>7}')
    rows = []
    for inst, pre_s in pre['per_instance_stats'].items():
        post_s = post['per_instance_stats'].get(inst)
        if not post_s or pre_s.get('n') == 0 or post_s.get('n') == 0:
            continue
        d_sigma = (post_s['stdev'] or 0) - (pre_s['stdev'] or 0)
        rows.append((inst, pre_s, post_s, d_sigma))
    rows.sort(key=lambda r: r[3])
    for inst, pre_s, post_s, d_sigma in rows:
        d_p50 = (post_s['p50'] or 0) - (pre_s['p50'] or 0)
        print(f'  {inst:<22} {pre_s["n"]:>7d} {post_s["n"]:>7d}  '
              f'{pre_s["p50"]:>8.1f} {post_s["p50"]:>8.1f} {d_p50:>+7.1f}  '
              f'{pre_s["stdev"]:>7.2f} {post_s["stdev"]:>7.2f} {d_sigma:>+7.2f}  '
              f'{pre_s["min"]:>7.1f} {post_s["min"]:>7.1f}')

    # Headline JIT A/B questions
    print()
    print('=== JIT A/B answers ===')
    f_pre = pre['fleet_stats']
    f_post = post['fleet_stats']
    print(f'  σ compression?           '
          f'fleet stdev {f_pre["stdev"]:.2f} → {f_post["stdev"]:.2f} '
          f'({(f_post["stdev"]-f_pre["stdev"])/f_pre["stdev"]*100:+.1f}%)')
    print(f'  p50 shift?               '
          f'fleet p50 {f_pre["p50"]:.1f} → {f_post["p50"]:.1f} '
          f'({f_post["p50"]-f_pre["p50"]:+.1f} fps)')
    print(f'  pct in NFO window 998-1002?  '
          f'{f_pre["pct_in_nfo_window"]:.4f} → {f_post["pct_in_nfo_window"]:.4f}')
    print(f'  pct within ±10 990-1010?     '
          f'{f_pre["pct_within_10"]:.4f} → {f_post["pct_within_10"]:.4f}')
    atl16_pre = pre['per_instance_stats'].get('atlanta:27016', {})
    atl16_post = post['per_instance_stats'].get('atlanta:27016', {})
    if atl16_pre and atl16_post and atl16_pre.get('stdev') and atl16_post.get('stdev'):
        print(f'  ATL:27016 normalization? '
              f'σ {atl16_pre["stdev"]:.2f} → {atl16_post["stdev"]:.2f}, '
              f'min {atl16_pre["min"]:.1f} → {atl16_post["min"]:.1f}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
