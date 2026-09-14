#!/usr/bin/env python3
"""
rtk.py - interactive protocol workbench for the Realtek/Microarray MOC
fingerprint bridge (3274:9011).

Implements the libfprint `realtek` driver transport so individual commands
can be issued and their raw responses inspected.

Usage:
    sudo python3 rtk.py init
    sudo python3 rtk.py cmd 05 13 01 00 00 00 00 00 00 00 00 00
    sudo python3 rtk.py script <file>     # one op per line
"""
import sys, time, struct
import usb.core, usb.util

VID, PID = 0x3274, 0x9011
EP_OUT = 0x01
EP_IN = 0x82

CMD_TIMEOUT = 1000
DATA_TIMEOUT = 5000
STATUS_TIMEOUT = 2000


def cmd_bulk(cmd2, param=b"\x00" * 4, addr=b"\x00" * 4, dlen=(0, 0)):
    return bytes(cmd2) + bytes(param) + bytes(addr) + bytes(dlen)


# pre-built command templates (from libfprint drivers/realtek/realtek.h)
CO_SELECT_SYSTEM = cmd_bulk(b"\x05\x13")
CO_GET_ENROLL_NUM = cmd_bulk(b"\x45\x0d", dlen=(2, 0))
CO_GET_TEMPLATE = cmd_bulk(b"\x45\x0e")
CO_START_CAPTURE = cmd_bulk(b"\x05\x05")
CO_FINISH_CAPTURE = cmd_bulk(b"\x45\x06", dlen=(5, 0))
CO_ACCEPT_SAMPLE = cmd_bulk(b"\x45\x08", dlen=(9, 0))
NOR_IDENTIFY_FEATURE = cmd_bulk(b"\x45\x22", dlen=(0x2A, 0))
NOR_ENROLL_BEGIN = cmd_bulk(b"\x05\x20")
CO_CHECK_DUPLICATE = cmd_bulk(b"\x45\x10", dlen=(0x22, 0))
NOR_ENROLL_COMMIT = cmd_bulk(b"\x85\x21")
CO_UPDATE_TEMPLATE = cmd_bulk(b"\x05\x11")
CO_DELETE_RECORD = cmd_bulk(b"\x05\x0f")
CO_CANCEL_CAPTURE = cmd_bulk(b"\x05\x07")


class Rtk:
    def __init__(self, vid=VID, pid=PID, do_reset=True):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise SystemExit(f"device {vid:04x}:{pid:04x} not found")
        self.dev.set_configuration()
        if do_reset:
            try:
                self.dev.reset()
                time.sleep(0.3)
            except Exception as e:
                print(f"  (reset: {e})")
        usb.util.claim_interface(self.dev, 0)
        self.claimed = True

    def release(self):
        if self.claimed:
            try:
                usb.util.release_interface(self.dev, 0)
            except Exception:
                pass
            self.claimed = False
        usb.util.dispose_resources(self.dev)

    def ctrl(self, req=0x07, value=0x000D, index=0x0000, length=8, timeout=CMD_TIMEOUT):
        try:
            return bytes(self.dev.ctrl_transfer(0xC0, req, value, index, length, timeout))
        except Exception as e:
            print(f"  ctrl error: {e}")
            return None

    def out(self, data, timeout=CMD_TIMEOUT):
        n = self.dev.write(EP_OUT, data, timeout)
        return n

    def rd(self, timeout=STATUS_TIMEOUT, maxlen=2048):
        try:
            return bytes(self.dev.read(EP_IN, maxlen, timeout))
        except usb.core.USBTimeoutError:
            return None
        except Exception as e:
            print(f"  read error: {e}")
            return None

    # ---- high level ----
    def send(self, cmd12, trans_data=None, msg_default=True, label=""):
        """Send a 12-byte command; follow the realtek driver flow.
        Returns (data_or_None, status_bytes_or_None)."""
        cmd_type = (cmd12[0] & 0xC0) >> 6
        tlen = (cmd12[11] << 8) | cmd12[10]
        print(f"  -> {'TX':<3} {cmd12.hex(' ')}"
              f"   [type={cmd_type} data_len={tlen}] {label}")
        try:
            self.out(cmd12)
        except Exception as e:
            print(f"     bulk OUT failed: {e}")
            return None, None

        data = None
        if cmd_type == 1:            # BULK_READ
            data = self.rd(DATA_TIMEOUT)
            print(f"     RX data ({len(data) if data else 0}): "
                  f"{data.hex(' ') if data else '-'}")
        elif cmd_type == 2:          # BULK_WRITE
            if trans_data:
                self.out(trans_data)
                print(f"     TX data ({len(trans_data)}): {trans_data.hex(' ')}")

        st = self.rd(STATUS_TIMEOUT)
        print(f"     RX status ({len(st) if st else 0}): {st.hex(' ') if st else '-'}")
        return data, st

    def init(self):
        print("[init] GET_DEVICE_INFO ctrl 0x07/0x000d len 8")
        info = self.ctrl()
        print(f"  device info: {info.hex(' ') if info else '-'}")
        print("[init] select system (param0=1)")
        self.send(cmd_bulk(b"\x05\x13", param=b"\x01\x00\x00\x00"), label="select_system")
        print("[init] get enroll num")
        d, s = self.send(CO_GET_ENROLL_NUM, label="get_enroll_num")
        return info, d, s


def parse_hex_args(args):
    return bytes(int(a, 16) for a in args)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    op = sys.argv[1]
    r = Rtk()

    if op == "init":
        r.init()

    elif op == "scan":
        """walk the whole command space to see which opcodes respond"""
        r.init()
        print("\n[scan] sending every cmd byte 0x00..0xff with second byte 0x00")
        for a in range(256):
            cmd = cmd_bulk(bytes([a, 0x00]))
            try:
                r.out(cmd)
                st = r.rd(300)
            except Exception as e:
                print(f"  {a:02x}: ERR {e}")
                continue
            if st:
                print(f"  {a:02x}: {st.hex(' ')}")

    elif op == "template":
        r.init()
        print("\n[template] try GET_TEMPLATE (45 0e) with various data_len")
        for n in (35 * 10, 38 * 10, 38, 35, 0x26 * 0x0a, 0, 1, 512, 350, 380):
            cmd = cmd_bulk(b"\x45\x0e", dlen=(n & 0xff, (n >> 8) & 0xff))
            print(f"\n-- data_len={n}")
            r.send(cmd, label="get_template")

    elif op == "cmd":
        r.init()
        data = parse_hex_args(sys.argv[2:])
        print(f"\n[cmd] raw {data.hex(' ')}")
        r.send(data, label="raw")

    elif op == "script":
        r.init()
        for line in open(sys.argv[2]):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            print(f"\n[script] {line}")
            if line.startswith("ctrl"):
                parts = line.split()
                req = int(parts[1], 16) if len(parts) > 1 else 0x07
                val = int(parts[2], 16) if len(parts) > 2 else 0x000D
                idx = int(parts[3], 16) if len(parts) > 3 else 0
                ln = int(parts[4]) if len(parts) > 4 else 8
                print("  ", r.ctrl(req, val, idx, ln))
            elif line.startswith("raw"):
                r.out(bytes(int(x, 16) for x in line.split()[1:]))
            else:
                r.send(bytes(int(x, 16) for x in line.split()))
    else:
        print(__doc__)
        r.release()
        return 1

    r.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
