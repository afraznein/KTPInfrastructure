#!/bin/bash
# Audit -- and with --fix, correct -- which kernel this host boots by default.
#
# Why: the fleet rebooted 2026-08-25 01:00 ET and Atlanta came back on
# 6.8.0-110-lowlatency while the other four hosts took 6.8.0-138. Atlanta's
# grubenv held saved_entry pinned to the LITERAL menu title
#   "Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency"
# -- the exact command KERNEL_EXPERIMENT_RUNBOOK.md used to prepare the
# preempt=full experiment. A name pin boots that kernel for as long as the
# entry exists, and because the pinned kernel IS the one running,
# /run/reboot-required clears and every reboot reports success. Silent and
# permanent until someone diffs uname across the fleet.
#
# The healthy fleet shape (Dallas, New York): GRUB_DEFAULT=saved in
# /etc/default/grub and saved_entry=1>0 in grubenv. "1>0" is positional --
# "Advanced options" submenu, first entry -- and grub-mkconfig emits kernels
# newest-first with -lowlatency ahead of -generic, so it tracks the newest
# lowlatency kernel across updates with no per-update step.
#
# Usage (on a game host, as root):
#   fix-grub-default-kernel.sh          # audit only, read-only, exit 1 on findings
#   fix-grub-default-kernel.sh --fix    # grub-set-default '1>0', then re-audit
#
# --fix corrects only the grubenv (GRUB_DEFAULT=saved) shape. It refuses when
# GRUB_DEFAULT is a positional literal (the Denver/Chicago shape) -- that fix
# means editing /etc/default/grub and re-running update-grub, a config change
# this script will not make for you. See docs/runbooks/GRUB_DEFAULT_KERNEL.md.
#
# It NEVER reboots. The correction takes effect at the next scheduled reboot.

set -euo pipefail

# Overridable for tests (fixtures of measured fleet states live in tests/unit).
GRUB_CFG="${KTP_GRUB_CFG:-/boot/grub/grub.cfg}"
GRUB_DEFAULT_FILE="${KTP_GRUB_DEFAULT_FILE:-/etc/default/grub}"
GRUB_ENV="${KTP_GRUB_ENV:-/boot/grub/grubenv}"
BOOT_DIR="${KTP_BOOT_DIR:-/boot}"
FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

fail=0
note() { echo "  $*"; }
finding() { echo "FINDING: $*"; fail=1; }

[ -r "$GRUB_CFG" ] || { echo "FATAL: cannot read $GRUB_CFG (run as root)" >&2; exit 2; }

running="${KTP_UNAME_R:-$(uname -r)}"

# Newest installed kernel, and newest lowlatency, by dpkg version order.
newest_ll="$(ls "$BOOT_DIR"/vmlinuz-*-lowlatency 2>/dev/null | sed 's|.*/vmlinuz-||' | sort -V | tail -1)"
newest_any="$(ls "$BOOT_DIR"/vmlinuz-* 2>/dev/null | sed 's|.*/vmlinuz-||' | sort -V | tail -1)"

# The Advanced submenu's entries, in menu order (tab-indented menuentry lines).
mapfile -t sub_entries < <(awk -F"'" '/^\tmenuentry /{print $2}' "$GRUB_CFG")

# Top-level order: "1>..." is only meaningful if entry 1 is the Advanced submenu.
top1="$(awk -F"'" '/^menuentry |^submenu /{n++; if (n==2) print $2}' "$GRUB_CFG")"

grub_default="$(grep -E '^GRUB_DEFAULT=' "$GRUB_DEFAULT_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"')"
# The baked default: the set default line that is not the ${next_entry}/${saved_entry} plumbing.
baked="$(grep -E '^\s*set default=' "$GRUB_CFG" | grep -v next_entry | tail -1 | sed 's/.*default="\(.*\)".*/\1/')"
saved="$(grep '^saved_entry=' "$GRUB_ENV" 2>/dev/null | cut -d= -f2- || true)"

echo "running kernel : $running"
echo "newest installed: $newest_any (newest lowlatency: ${newest_ll:-none})"
echo "GRUB_DEFAULT    : ${grub_default:-<unset>}"
echo "baked default   : ${baked:-<none>}"
echo "saved_entry     : ${saved:-<none>}"
echo "menu entry 1    : ${top1:-<none>}"
echo "submenu[0]      : ${sub_entries[0]:-<none>}"

# Resolve what the next reboot boots, for the shapes the fleet actually has.
resolve_positional() {  # "1>N" -> menu title, or empty if unresolvable
    local pos="$1" idx
    [ "${pos%%>*}" = "1" ] || return 0
    idx="${pos#*>}"
    [ "$top1" = "Advanced options for Ubuntu" ] || return 0
    echo "${sub_entries[$idx]:-}"
}

effective=""
shape=""
if { [ "$baked" = '${saved_entry}' ] || [ "$grub_default" = "saved" ]; } && [ -n "$saved" ]; then
    shape="saved"
    # A saved_entry containing a space is a menu TITLE, not a position.
    if [[ "$saved" == *" "* ]]; then
        finding "saved_entry is a LITERAL TITLE pin: '$saved'"
        note "this boots that exact kernel forever; kernel updates install, reboot-required"
        note "clears (the pinned kernel is running), and the update never takes effect."
        effective="${saved##*>}"
    else
        effective="$(resolve_positional "$saved")"
    fi
elif [ -n "$grub_default" ] && [ "$grub_default" != "saved" ]; then
    shape="literal"
    effective="$(resolve_positional "$baked")"
    finding "GRUB_DEFAULT is a positional literal ('$grub_default'), not 'saved'"
    note "positional literals go stale as the kernel list changes; fleet canon is"
    note "GRUB_DEFAULT=saved + saved_entry=1>0 (Dallas / New York shape)."
    if [ "$grub_default" != "$baked" ]; then
        pending="$(resolve_positional "$grub_default")"
        finding "/etc/default/grub ('$grub_default' -> '${pending:-?}') disagrees with the baked grub.cfg ('$baked' -> '${effective:-?}')"
        note "the next update-grub (any kernel update runs one) re-bakes '$grub_default'."
    fi
fi

if [ -n "$effective" ]; then
    echo "next boot       : $effective"
    case "$effective" in
        *"$newest_ll"*) : ;;
        *) finding "next boot ('$effective') is not the newest lowlatency kernel ($newest_ll)" ;;
    esac
else
    finding "could not resolve the effective default entry -- inspect $GRUB_CFG by hand"
fi

if [ "$FIX" = 1 ]; then
    if [ "$shape" != "saved" ]; then
        echo "REFUSING --fix: GRUB_DEFAULT is not 'saved'. Fix /etc/default/grub +" >&2
        echo "update-grub by hand -- see docs/runbooks/GRUB_DEFAULT_KERNEL.md." >&2
        exit 2
    fi
    if [ "$top1" != "Advanced options for Ubuntu" ] || [[ "${sub_entries[0]:-}" != *lowlatency* ]]; then
        echo "REFUSING --fix: menu shape unexpected (entry 1 = '$top1', submenu[0] = '${sub_entries[0]:-}')" >&2
        exit 2
    fi
    grub-set-default '1>0'
    echo "grubenv now     : $(grep '^saved_entry=' "$GRUB_ENV")"
    echo "DONE. Takes effect at the next reboot -- this script never reboots, and on"
    echo "this fleet a reboot is an operator action (production, 03:00 ET window)."
    exit 0
fi

exit $fail
