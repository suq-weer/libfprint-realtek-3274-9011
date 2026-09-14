#!/usr/bin/env python3
"""
rtk_enroll.py - drive a full MOC enrollment on 3274:9011 directly over USB,
printing every raw response, then dump the template table so its layout can
be decoded.

Needs a finger on the sensor when prompted.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rtk2 import Rtk, cmd_bulk, init

PURPOSE_ENROLL = 0x04
SUB_FINGER_01 = 0xFF
UID_PAYLOAD_LEN = 32
SAMPLES = 3
FINGER_TIMEOUT = 90      # seconds to wait for a press
LIFT_TIMEOUT = 30


def drain_data(pkts):
    """pkts: list of (ms, bytes). data packet(s) then 5-byte status."""
    data = b''.join(d for _, d in pkts[:-1]) if len(pkts) > 1 else b''
    status = pkts[-1][1] if pkts else b''
    return data, status


def show(label, pkts):
    print(f"  [{label}] " + ("; ".join(f"{len(d)}B:{d[:16].hex(' ')}"
          + ("..." if len(d) > 16 else "") for _, d in pkts) if pkts else "(no response)"),
          flush=True)


def main():
    r = Rtk()
    try:
        init(r, verbose=False)
        print("[init] device info: " + r.ctrl().hex(' '), flush=True)

        # --- slot selection: try the normal way first ---
        pk = r.issue(cmd_bulk(b"\x45\x0e", dlen=35), read_timeout=1500, verbose=False)
        print("[get_template 35B] " + (pk[-1][1].hex(' ') if pk else 'none'), flush=True)

        # --- enroll begin, slot 0 ---
        pk = r.issue(cmd_bulk(b"\x05\x20", param=b"\x00\x00\x00\x00"),
                     read_timeout=1500, verbose=False)
        show("enroll_begin(slot0)", pk)

        for sample in range(1, SAMPLES + 1):
            print(f"\n>>> PRESS your finger on the sensor (sample {sample}/{SAMPLES})",
                  flush=True)
            pk = r.issue(cmd_bulk(b"\x05\x05"), read_timeout=1500, verbose=False)
            show("start_capture", pk)

            t0 = time.time()
            got = False
            while time.time() - t0 < FINGER_TIMEOUT:
                pk = r.issue(cmd_bulk(b"\x45\x06", dlen=5), read_timeout=1200, verbose=False)
                data, status = drain_data(pk)
                if data and data[0] == 0:
                    print(f"    captured after {time.time()-t0:.1f}s  "
                          f"data={data.hex(' ')} status={status.hex(' ')}", flush=True)
                    got = True
                    break
                time.sleep(0.15)
            if not got:
                print("    !! no capture within window", flush=True)
                break

            print(">>> LIFT your finger", flush=True)
            pk = r.issue(cmd_bulk(b"\x45\x08", param=bytes([PURPOSE_ENROLL, 0, 0, 0]), dlen=9),
                         read_timeout=1500, verbose=False)
            show("accept_sample(enroll)", pk)

            # wait for lift: poll finish_capture until it reports nothing
            t0 = time.time()
            while time.time() - t0 < LIFT_TIMEOUT:
                pk = r.issue(cmd_bulk(b"\x45\x06", dlen=5), read_timeout=1000, verbose=False)
                data, _ = drain_data(pk)
                if data and data[0] != 0:
                    break
                time.sleep(0.15)

        # --- duplicate check ---
        print("\n[check_duplicate]", flush=True)
        pk = r.issue(cmd_bulk(b"\x45\x10", dlen=0x22), read_timeout=3000, verbose=False)
        show("check_duplicate", pk)

        # --- commit ---
        uid = b"rtk9011probe" + b"\x00" * (UID_PAYLOAD_LEN - 13)
        payload = uid[:UID_PAYLOAD_LEN]
        print("\n[commit]", flush=True)
        pk = r.issue(cmd_bulk(b"\x85\x21", param=bytes([SUB_FINGER_01, 0, 0, 0]),
                              dlen=UID_PAYLOAD_LEN),
                     data=payload, read_timeout=5000, verbose=False)
        show("commit", pk)

        # --- cancel ---
        pk = r.issue(cmd_bulk(b"\x05\x07", param=bytes([PURPOSE_ENROLL, 0, 0, 0])),
                     read_timeout=1500, verbose=False)
        show("cancel_capture", pk)

        # --- now read back the template table ---
        print("\n=== template table after enroll ===", flush=True)
        for n in (35, 32, 31, 16, 10, 8, 4, 2, 1, 36, 70, 350):
            pk = r.issue(cmd_bulk(b"\x45\x0e", dlen=n), read_timeout=1500, verbose=False)
            data, status = drain_data(pk)
            print(f"  dlen={n:4d}  data({len(data)})={data.hex(' ')}  status={status.hex(' ')}",
                  flush=True)

        print("\n=== storage count ===", flush=True)
        pk = r.issue(cmd_bulk(b"\x45\x0d", dlen=2), read_timeout=1500, verbose=False)
        show("get_enroll_num", pk)
    finally:
        r.release()


if __name__ == "__main__":
    main()
