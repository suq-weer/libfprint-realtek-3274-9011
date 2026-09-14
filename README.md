# libfprint-realtek-3274-9011

Linux support for the **Microarray / Realtek MOC fingerprint sensor `3274:9011`**
("Generic Realtek USB2.0 Finger Print Bridge"), as found in laptops such as the
**Mechrevo Wujie 14**.

Upstream libfprint already ships a `realtek` driver that recognises this sensor,
but enrollment always fails. This repository contains the reverse-engineered
root cause, a small patch that fixes it, and the tooling used to work it out.

**English** | [简体中文](README.zh-CN.md)

---

> ## ⚠️ Read this first
>
> ### This was produced by an AI agent
>
> Every artifact here — the protocol analysis, the patch, the scripts and this
> document — was produced by an **AI coding agent (DeepSeek Harness)** working
> under human direction, by reverse-engineering a Windows driver package and
> probing real hardware.
>
> **Consequences you should take seriously:**
>
> - **It is not upstream-reviewed.** No maintainer has audited this patch.
> - **It modifies an authentication component.** `libfprint` sits on the
>   `fprintd` → PAM path. A bug here can affect how you log in.
> - **It has been tested on exactly one device** (`3274:9011`, one laptop).
>   Not on `3274:9003`, not on `3274:9008`, not on any other Realtek MOC part.
> - **The reasoning may contain errors.** The conclusions below are backed by
>   the measurements shown, but treat them as claims to verify, not facts.
>
> ### Do not blindly copy commands
>
> Read `install.sh` and `build.sh` before running them. They install a library
> into `/usr/lib64` and restart `fprintd`. Keep a backup and know how to roll
> back.
>
> ### Not affiliated
>
> Not affiliated with Realtek, Microarray, Mechrevo, or the libfprint project.
> "Realtek", "Windows Hello" etc. are trademarks of their owners.

---

## Status

Verified on the author's machine (Fedora 44, kernel 6.x):

| Capability | Status | Evidence |
|---|---|---|
| libfprint recognises the device | ✅ | `Device name: Realtek USB2.0 Finger Print Bridge` |
| Init / read template table | ✅ | 10 slots × 35 bytes, status `0x00` |
| Enroll (libfprint example) | ✅ | `Enroll stage 8 of 8 passed` → `Enrollment complete!` |
| Verify (libfprint example) | ✅ | `FPI_MATCH_SUCCESS` → `MATCH!` |
| Clear storage | ✅ | `Clear storage successful!` |
| **fprintd enroll** | ✅ | `Enroll result: enroll-stage-passed` ×8 → `enroll-completed` |
| **fprintd verify** | ✅ | `Verify result: verify-match (done)` |

```
$ fprintd-list $USER
Fingerprints for user ... on Realtek USB2.0 Finger Print Bridge (press):
 - #0: right-index-finger

$ fprintd-verify $USER
Verify result: verify-match (done)
```

---

## Hardware

```
idVendor   0x3274
idProduct  0x9011
Product    "Realtek USB2.0 Finger Print Bridge"
Interface  0xFF / 0x02 / 0x00  (vendor specific)
Endpoints  0x01 OUT bulk, 0x82 IN bulk   (0x83/0x84 interrupt, unused)
```

This is a **Match-on-Chip (MOC)** sensor: the fingerprint is captured *and*
matched inside the chip. It never exports fingerprint images, so libfprint
exposes no `CAPTURE` feature for it. That is a property of the hardware, not a
missing feature.

---

## Root cause

Upstream `libfprint/drivers/realtek/realtek.c` sends, for every supported model:

```c
co_select_system.param[0] = 0x01;   /* command 05 13 */
```

**On `3274:9011`, `param = 1` locks the on-chip template store.** Measured on
real hardware (each trial preceded by a fresh device state), immediately
followed by `GET_TEMPLATE (45 0e)` with a 350-byte request:

| `select_os` `param[0]` | `GET_TEMPLATE` status |
|---|---|
| not sent / `0` / `2` … `11` | `0x00` ✅ |
| **`1`** | **`0x01` ❌** |

With the store locked, `GET_TEMPLATE` also refuses to return more than 35 bytes
(one record), so the driver cannot read the template table to find a free slot
and aborts with `Status check failed`. Recovery is immediate:
`select_os(1)` followed by `select_os(0)` or `select_os(2)` restores access.

> **Note on a widespread claim:** you may find references to a "required 4-step
> `select_os` handshake (params 0→1→2→3)". That sequence happens to end on
> `3`, i.e. on a *non-1* parameter — which is why it appears to work. The
> handshake is not itself required; the parameter value is what matters.

### Two further issues fixed here

1. **USB reset breaks the handle.** `dev_probe()` and `dev_init()` both called
   `g_usb_device_reset()`. This sensor re-enumerates on reset, leaving the
   `GUsbDevice` handle stale, which caused intermittent
   `USB error ... Operation timed out`. Raw libusb probes were 9/9 reliable
   without a reset; removing both resets gave 5/5 probe and 6/6 open success.
2. **Unthrottled polling.** The capture-status poll re-entered its state
   immediately, producing roughly **8,000 USB transactions per second**
   (45 MB of debug log in 11 s). Paced at 20 ms.

### And one device-side cleanup

The sensor shipped with a pre-existing template in slot 0, which makes
enrollment of the same finger report `duplicate`. It is **not** a backdoor —
it holds a UID/index, not biometric data, and libfprint additionally checks
`fp_print_equal()` against the user's stored prints, so it cannot authenticate
anyone. Clear it with `delete_record(0xff)` (see `tools/`), or simply enroll
through `fprintd`, which handles it.

Full protocol details: **[docs/PROTOCOL.md](docs/PROTOCOL.md)**.

---

## The patch

`realtek-3274-9011.patch` — 3 files, +34 / −14, applies cleanly to upstream
libfprint **v1.94.100**.

| File | Change |
|---|---|
| `libfprint/drivers/realtek/realtek.c` | add `3274:9011` with `REALTEK_QUIRK_SELECT_OS_0`; drop the two resets |
| `libfprint/drivers/realtek/realtek.h` | `FP_RTK_CAPTURE_POLL_MS 20` |
| `data/autosuspend.hwdb` | add `usb:v3274p9011*` |

The quirk is gated on `driver_data`, so **no other Realtek model changes
behaviour**.

---

## Build & install

Requires: `meson`, `ninja`, `gcc`, `pkg-config` and the dev packages for
`glib2`, `gusb`, `libusb`, `libgudev`, `openssl`, `pixman`.
`build.sh` tells you what is missing if you try to build without them.

```bash
git clone https://github.com/RChips22/libfprint-realtek-3274-9011
cd libfprint-realtek-3274-9011

./build.sh                 # fetch upstream + apply patch + build (no root needed)
sudo ./install.sh          # or: pkexec ./install.sh
```

> `build.sh` also works around an **unrelated upstream bug** in libfprint
> v1.94.100: `tests/meson.build` iterates a dict with a single loop variable,
> which newer meson rejects (`Foreach expects exactly 2 variables ...`). It was
> fixed later in master. The workaround is a one-line `sed`, logged when applied,
> and deliberately kept out of `realtek-3274-9011.patch` so that the patch stays
> focused enough to upstream.

Then enroll:

```bash
fprintd-enroll $USER       # press the sensor 8 times
fprintd-verify $USER
fprintd-list   $USER
```

### Uninstall / roll back

```bash
sudo dnf reinstall libfprint          # Fedora / Copr
sudo apt install --reinstall libfprint-2-2   # Debian / Ubuntu
```

or restore the backup that `install.sh` made:

```bash
sudo cp -a /var/backups/libfprint-2.so.2.0.0.pre-9011 /usr/lib64/libfprint-2.so.2.0.0
sudo ldconfig && sudo systemctl restart fprintd
```

---

## Boundaries — what this does **not** do

- **No PAM configuration.** This reaches the `fprintd` layer only. To use the
  sensor for login/unlock you must add `pam_fprintd.so` to your PAM stack
  yourself — that changes authentication behaviour and is your call.
- **No image capture.** Match-on-chip hardware; there are no images to capture.
- **`identify` (1:N) and single-`delete` were not individually tested.**
  `enroll`, `verify`, `list` and `clear_storage` were.
- **`3274:9008` is deliberately not enabled.** The Windows INF covers it
  alongside `9011`, but no such hardware was available to test, so the patch
  does not claim support for it.
- **One machine, one unit.** Timing-sensitive behaviour (the reset race) may
  differ on other hosts or kernels.
- **No warranty.** See LICENSE.

---

## Repository layout

| Path | What |
|---|---|
| `realtek-3274-9011.patch` | the patch |
| `build.sh` / `install.sh` | fetch, patch, build, install |
| `docs/PROTOCOL.md` | reverse-engineered USB protocol |
| `docs/SECURITY-NOTES.md` | the pre-existing template & supply-chain notes |
| `tools/rtk.py` | protocol workbench (init / template R-W / raw commands) |
| `tools/rtk2.py` | packet-level capture with pipe resync |
| `tools/rtk_probe.c` | standalone libusb validation program |
| `tools/rtk_enroll.py` | raw on-chip enrollment (needs a finger) |
| `tools/ghidra_wbdi_usb.java` | Ghidra script used to locate the USB layer |
| `udev/60-fingerprint-3274-9011.rules` | grants the logged-in user access (debugging convenience) |

The Windows driver package (`MicroarrayMocWbdi.dll` and friends) is **not**
included — those are proprietary vendor binaries. The analysis references them
but does not redistribute them.

---

## Credits & license

- Patch and tooling: **LGPL-2.1-or-later**, matching libfprint. See [LICENSE](LICENSE).
- Built against [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint)
  by the libfprint contributors — in particular the in-tree `realtek` driver
  (© Realtek Corp.), which does the heavy lifting.
- Prior art consulted: the "4-step handshake" observation from
  [xiaomaogou66/Mechrevo-Wujie14-Unlock](https://github.com/xiaomaogou66/Mechrevo-Wujie14-Unlock).
  This repository corrects that explanation and fixes two additional bugs.
- Analysis, patch and documentation produced by an AI agent (DeepSeek Harness)
  under human direction.

If this saves you time, the most useful thing you can do is **get the quirk
upstreamed to libfprint** so nobody needs a local build.
