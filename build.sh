#!/bin/bash
#
# build.sh - fetch upstream libfprint, apply the 3274:9011 patch, and build it.
#
#   ./build.sh              # clones libfprint v1.94.100 into ./libfprint-src
#   ./build.sh /path/to/dir # use a different build location
#
# The result is a patched libfprint-2.so.2.0.0 in
#   <dir>/builddir/libfprint/
#
# Nothing in this script touches your system; run ./install.sh afterwards.
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$ROOT/libfprint-src}"
VERSION="1.94.100"
TARBALL_URL="https://gitlab.freedesktop.org/libfprint/libfprint/-/archive/v${VERSION}/libfprint-v${VERSION}.tar.gz"

echo "==> Checking build dependencies"
missing=0
for tool in meson ninja gcc pkg-config; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "    MISSING tool: $tool" >&2
        missing=1
    fi
done
for dep in glib-2.0 gio-2.0 gusb libusb-1.0; do
    if ! pkg-config --exists "$dep" 2>/dev/null; then
        echo "    MISSING pkg-config module: $dep" >&2
        missing=1
    fi
done
if [ "$missing" -ne 0 ]; then
    cat >&2 <<'EOF'

Install the missing pieces first, e.g.
  Fedora : sudo dnf install meson ninja-build gcc pkgconf-pkg-config \
                          glib2-devel libgusb-devel libusb1-devel \
                          libgudev-devel openssl-devel pixman-devel
  Debian : sudo apt install meson ninja-build gcc pkg-config \
                          libglib2.0-dev libgusb-dev libusb-1.0-0-dev \
                          libgudev-1.0-dev libssl-dev libpixman-1-dev
  Arch   : sudo pacman -S meson ninja gcc pkgconf glib2 libgusb libusb \
                          libgudev openssl pixman
EOF
    exit 1
fi

# ---------------------------------------------------------------------------
echo "==> Preparing source in $SRC"
if [ ! -d "$SRC/libfprint" ]; then
    rm -rf "$SRC"; mkdir -p "$SRC"
    if command -v git >/dev/null 2>&1 && \
       git clone --depth 1 --branch "v${VERSION}" \
           https://gitlab.freedesktop.org/libfprint/libfprint.git "$SRC" 2>/dev/null; then
        echo "    cloned via git"
    else
        echo "    cloning failed, falling back to tarball"
        rm -rf "$SRC"; mkdir -p "$SRC"
        curl -L --fail -o "$SRC/libfprint.tar.gz" "$TARBALL_URL"
        tar xzf "$SRC/libfprint.tar.gz" -C "$SRC" --strip-components=1
        rm -f "$SRC/libfprint.tar.gz"
        echo "    downloaded tarball"
    fi
fi

# ---------------------------------------------------------------------------
echo "==> Applying realtek-3274-9011.patch"
cd "$SRC"
if grep -q "REALTEK_QUIRK_SELECT_OS_0" libfprint/drivers/realtek/realtek.c 2>/dev/null; then
    echo "    already applied, skipping"
else
    patch -p1 --forward < "$ROOT/realtek-3274-9011.patch"
fi

# ---------------------------------------------------------------------------
# Unrelated upstream bug in v1.94.100, fixed later in master.
# tests/meson.build iterates a dict with a single loop variable, which meson
# rejects with: "Foreach expects exactly 2 variables for iterating over
# objects of type dict". It is only reached when introspection is disabled
# (the configuration used here), so without this the build fails.
if grep -q 'foreach driver_test: drivers_tests' tests/meson.build 2>/dev/null; then
    echo "==> Patching upstream meson bug in tests/meson.build"
    sed -i 's/foreach driver_test: drivers_tests/foreach driver_test, _args : drivers_tests/' tests/meson.build
fi

# ---------------------------------------------------------------------------
echo "==> Configuring"
# doc / introspection / tests need extra deps we do not require here.
meson setup builddir \
    -Ddrivers=default \
    -Ddoc=false \
    -Dintrospection=false \
    -Dgtk-examples=false \
    -Dinstalled-tests=false \
    --reconfigure 2>/dev/null || \
meson setup builddir \
    -Ddrivers=default \
    -Ddoc=false \
    -Dintrospection=false \
    -Dgtk-examples=false \
    -Dinstalled-tests=false

echo "==> Building"
ninja -C builddir

echo
echo "================= BUILD OK ================="
ls -l "$SRC/builddir/libfprint/libfprint-2.so.2.0.0"
echo "============================================"
echo
echo "Verify the 3274:9011 entry is present:"
echo "    strings -a $SRC/builddir/libfprint/libfprint-2.so.2.0.0 | grep -c realtek"
echo
echo "Next:  sudo ./install.sh $SRC"
