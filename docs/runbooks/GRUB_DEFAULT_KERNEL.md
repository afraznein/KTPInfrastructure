# GRUB default-kernel audit and repair

**Why this runbook exists.** At the 2026-08-25 01:00 ET reboot, Atlanta came back on
`6.8.0-110-lowlatency` while the other four game hosts took `6.8.0-138`. Atlanta's grubenv held

```
saved_entry=Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency
```

— a pin **by literal menu title**, left behind by the `preempt=full` kernel experiment
(`docs/KERNEL_EXPERIMENT_RUNBOOK.md` used exactly that `grub-set-default` form; it has since been
corrected). The failure is silent and self-sustaining: kernel updates install normally, but because
the pinned kernel *is* the one running, `/run/reboot-required` clears at each reboot and every reboot
reports success. Nothing flags it — the running kernel simply stops tracking updates, forever.

## Fleet canon

`GRUB_DEFAULT=saved` in `/etc/default/grub`, plus `saved_entry=1>0` in grubenv — the shape Dallas and
New York run. `1>0` is positional (the "Advanced options for Ubuntu" submenu, first entry), and
grub-mkconfig emits kernels newest-first with `-lowlatency` ahead of `-generic`, so it tracks the
newest lowlatency kernel across updates with no per-update step.

## Audit / fix

```bash
# on the host, as root -- audit is read-only, exits 1 on findings
scripts/fix-grub-default-kernel.sh

# rewrite grubenv to the canon (only valid when GRUB_DEFAULT=saved)
scripts/fix-grub-default-kernel.sh --fix
```

`--fix` runs `grub-set-default '1>0'` after verifying the menu shape. It **never reboots** — the
correction takes effect at the next reboot, which on this fleet is an operator action.

## What the 2026-08-25 audit measured (host by host)

| host | shape | next boot | finding |
|---|---|---|---|
| Atlanta | `saved` + literal-title pin | `6.8.0-110-lowlatency` | the incident. Fix: `--fix`, then an operator-scheduled reboot |
| Dallas | `saved` + `1>0` | newest lowlatency | clean — the control |
| New York | `saved` + `1>0` | newest lowlatency | clean |
| Denver | `GRUB_DEFAULT="1>2"` literal; grub.cfg still bakes `1>0` | right kernel *today* | the next `update-grub` (any kernel update runs one) re-bakes `1>2`, which in Denver's menu is `6.8.0-110-lowlatency` — a silent downgrade armed and waiting |
| Chicago | `GRUB_DEFAULT="1>2"` literal, baked as-is | `6.8.0-138-generic` per grub.cfg | next reboot drops the `-lowlatency` flavour. (It currently *runs* lowlatency, so the baked default and the last boot disagree — Linode's boot path may not read this grub.cfg the way a baremetal does; verify from the console before relying on either reading) |

## Converting a literal-GRUB_DEFAULT host (Denver, Chicago) to canon

`--fix` deliberately refuses these — the fix is a config edit, not a grubenv write:

```bash
cp -a /etc/default/grub /root/default-grub.pre-canon-$(date +%Y%m%d)   # backup OUTSIDE any deploy path
sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub
update-grub
grub-set-default '1>0'
scripts/fix-grub-default-kernel.sh    # must now report clean
```

Then reboot at the operator's discretion. ⛔ Never a name pin: `grub-set-default` with a menu title
recreates the Atlanta failure — if an experiment needs a specific older kernel, pin positionally,
write down where the pin is, and file the removal as part of the experiment's rollback.
