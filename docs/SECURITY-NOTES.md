# Security notes

Two things people reasonably ask about this project, plus one trap worth
knowing about if you patch an authentication library yourself.

---

## 1. Is the pre-existing template in the sensor a backdoor?

**No — but the question is a good one, and it is worth understanding why.**

### What is actually stored

After the four-step-free init described in `PROTOCOL.md`, `GET_TEMPLATE`
(`45 0e`, 350 bytes) returns the on-chip template table: **10 slots × 35 bytes**.
On a fresh unit, slot 0 held:

```
01 01 f5 a8 d7 54 bb 80 55 38 cf 25 86 33 c8 2d
9d e7 54 a5 70 1f b5 16 35 0d 74 0c e9 7a 91 38 7a c4 9a
```

Record layout (derived from the driver's `fp_print_from_data` / `fp_list_cb`):

| Offset | Length | Meaning |
|---|---|---|
| 0 | 1 | valid flag (0 = empty slot) |
| 1 | 1 | unknown |
| 2 | 1 | finger id (`0xFF`) |
| 3 | 28 | UID |
| 31 | 4 | trailer |

**This is an index/UID record, not biometric data.** The fingerprint template
itself never leaves the chip; matching happens in hardware.

### Why it cannot authenticate anyone

libfprint does not trust the chip's "match" verdict on its own. It takes the
record the chip returns, builds an `FpPrint` from it, and compares it against
the prints stored for that user:

```c
case FPI_PRINT_RAW:
  return g_variant_equal (self->data, other->data);   /* finger + UID must match exactly */
```

The factory UID was never written into any user's `fprintd` database
(`/var/lib/fprint/`), so there is nothing for it to match against.

### What it actually causes

A functional annoyance: the slot is occupied, and the on-chip matcher reports
`duplicate` when the same finger is enrolled again. Clear it with
`delete_record(0xff)` (`tools/rtk.py`), or just enroll through `fprintd`.

It most likely came from factory provisioning or from a previous Windows
enrollment.

---

## 2. The ldconfig trap (worth knowing even if you skip the rest)

When replacing a system library by hand, do **not** put the backup next to it:

```bash
# WRONG
cp -a /usr/lib64/libfprint-2.so.2.0.0 /usr/lib64/libfprint-2.so.2.0.0.pre-9011
```

`ldconfig` treats any `lib*.so*` file in a library directory as a candidate
library. The name `libfprint-2.so.2.0.0.pre-9011` sorts as a *newer* version
than `libfprint-2.so.2.0.0`, so `ldconfig` repointed the soname symlink at the
backup:

```
/usr/lib64/libfprint-2.so.2 -> libfprint-2.so.2.0.0.pre-9011   # the OLD library
```

The failure mode is nasty because it is silent: `rpm -q` reported the new
package, the device was still detected, and `install.sh` looked successful —
but the process was executing the **old** code, so enrollment still failed.

`install.sh` in this repository:

- keeps the backup in `/var/backups/` (outside the search path),
- moves away any stray `libfprint-2.so.2.0.0.*` left in the library directory,
- runs `ldconfig` after installing.

Verify with:

```bash
readlink -f /usr/lib64/libfprint-2.so.2     # must end in libfprint-2.so.2.0.0
rpm -V libfprint                            # should print nothing
```

---

## 3. Supply-chain caveat for this project itself

This patch modifies an **authentication component**. `fprintd` loads
`libfprint` as root and sits on the PAM path. Practical advice:

- Prefer building from this repository's **readable patch** rather than
  trusting a prebuilt binary from anywhere.
- Keep the original library backed up and know your rollback command
  (see `README.md`).
- Verify what is actually loaded, not just what is installed
  (`readlink -f`, `rpm -V`, or compare the id table as shown above).
- The long-term fix is to **get the quirk upstreamed** to libfprint, so no
  local build is needed at all.

### What was audited here

- The patch is 34 added lines across 3 files, all shown in
  `realtek-3274-9011.patch`; it adds an ID, one quirk-gated parameter value,
  a polling delay, and an hwdb entry. It makes no network, exec or file access.
- The tools in `tools/` communicate only over USB via libusb. They are plain
  source; build them yourself rather than trusting any binary.
- The Windows vendor DLLs referenced during the analysis are **not**
  redistributed here, and they are not executed on Linux.
