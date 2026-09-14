#!/bin/bash
#
# install.sh - install the patched libfprint built by ./build.sh
#
#   sudo ./install.sh [build-dir]
#   pkexec ./install.sh [build-dir]        # desktop polkit prompt
#
# What it does
#   1. backs up the current libfprint-2.so.2.0.0
#   2. installs the patched library over it
#   3. runs ldconfig, updates udev/hwdb, restarts fprintd
#
# IMPORTANT - the backup is placed OUTSIDE the library search path.
# A file named like "libfprint-2.so.2.0.0.<something>" inside /usr/lib64 is
# picked up by ldconfig as a *newer* version of the library, and ldconfig then
# repoints the libfprint-2.so.2 soname at the backup. The system would appear
# to have the patched library while actually loading the old one.
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$ROOT/libfprint-src}"
SO_BUILT="$SRC/builddir/libfprint/libfprint-2.so.2.0.0"

SO_DEST="/usr/lib64/libfprint-2.so.2.0.0"
[ -d /usr/lib/x86_64-linux-gnu ] && [ ! -d /usr/lib64 ] && SO_DEST="/usr/lib/x86_64-linux-gnu/libfprint-2.so.2.0.0"
BAK="/var/backups/libfprint-2.so.2.0.0.pre-9011"

if [ -n "${PKEXEC_UID:-}" ]; then
    TARGET_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
elif [ -n "${SUDO_USER:-}" ]; then
    TARGET_USER="$SUDO_USER"
else
    TARGET_USER="${USER:-$(id -un)}"
fi

if [ ! -f "$SO_BUILT" ]; then
    echo "ERROR: $SO_BUILT not found - run ./build.sh first" >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (sudo $0 / pkexec $0)" >&2
    exit 1
fi

echo "==> Built library : $SO_BUILT"
echo "==> Destination   : $SO_DEST"
echo "==> User          : ${TARGET_USER:-<unknown>}"

if [ -f "$SO_DEST" ] && [ ! -f "$BAK" ]; then
    mkdir -p /var/backups
    cp -a "$SO_DEST" "$BAK" && echo "==> Backed up previous library -> $BAK"
fi

# Remove any stray copy left inside the library path by an earlier attempt,
# otherwise ldconfig may keep preferring it.
for stray in /usr/lib64/libfprint-2.so.2.0.0.* /usr/lib/x86_64-linux-gnu/libfprint-2.so.2.0.0.*; do
    [ -e "$stray" ] || continue
    echo "==> Moving stray library out of the search path: $stray"
    mkdir -p /var/backups
    mv -f "$stray" "/var/backups/$(basename "$stray")"
done

echo "==> Installing"
install -m 0755 "$SO_BUILT" "$SO_DEST"

echo "==> Running ldconfig / udev / fprintd"
ldconfig 2>/dev/null || true
systemd-hwdb update 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=usb 2>/dev/null || true
systemctl restart fprintd 2>/dev/null || true
sleep 1

echo
echo "================= INSTALLED ================="
echo "soname resolves to: $(readlink -f "$SO_DEST" 2>/dev/null || echo "$SO_DEST")"
ls -l "$SO_DEST"
[ -f "$BAK" ] && echo "backup            : $BAK"
echo "============================================="
echo
echo "Next steps:"
echo "    fprintd-list   ${TARGET_USER:-<user>}"
echo "    fprintd-enroll ${TARGET_USER:-<user>}     # press the sensor 8 times"
echo "    fprintd-verify ${TARGET_USER:-<user>}"
echo
echo "To uninstall, restore the backup and run ldconfig:"
echo "    sudo cp -a $BAK $SO_DEST && sudo ldconfig && sudo systemctl restart fprintd"
