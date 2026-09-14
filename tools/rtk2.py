#!/usr/bin/env python3
"""
rtk2.py - careful packet-level protocol explorer for 3274:9011.

Reads every IN packet separately (with timestamps) so response framing is
visible, and drains the pipe before each command so results cannot desync.
"""
import sys, time
import usb.core, usb.util

VID, PID = 0x3274, 0x9011
EP_OUT, EP_IN = 0x01, 0x82


def cmd_bulk(cmd2, param=b"\x00" * 4, addr=0, dlen=0):
    return (bytes(cmd2) + bytes(param) + addr.to_bytes(4, 'little') +
            (dlen & 0xff).to_bytes(1, 'little') + ((dlen >> 8) & 0xff).to_bytes(1, 'little'))


class Rtk:
    def __init__(self, vid=VID, pid=PID):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise SystemExit("device not found")
        self.dev.set_configuration()
        self.dev.reset()
        time.sleep(0.4)
        usb.util.claim_interface(self.dev, 0)
        # prime: send a harmless BULK_ONLY command so the pipe is in a known state
        self.drain()

    def drain(self, timeout=250):
        pkts = []
        while True:
            try:
                d = bytes(self.dev.read(EP_IN, 4096, timeout))
                if not d:
                    break
                pkts.append(d)
            except usb.core.USBTimeoutError:
                break
            except Exception:
                break
        return pkts

    def ctrl(self, req=0x07, value=0x000D, index=0, length=8):
        return bytes(self.dev.ctrl_transfer(0xC0, req, value, index, length, 2000))

    def issue(self, cmd12, data=None, label="", read_timeout=1500, verbose=True):
        """Send one command and capture every IN packet it produces."""
        pre = self.drain()
        if pre and verbose:
            print(f"     (drained {sum(len(p) for p in pre)} stale bytes)")
        self.dev.write(EP_OUT, cmd12, 2000)
        if data:
            self.dev.write(EP_OUT, data, 2000)
        pkts = []
        t0 = time.time()
        while True:
            try:
                d = bytes(self.dev.read(EP_IN, 4096, read_timeout))
            except usb.core.USBTimeoutError:
                break
            except Exception as e:
                print("     read err", e)
                break
            if not d:
                break
            pkts.append((round((time.time() - t0) * 1000), d))
        if verbose:
            ct = (cmd12[0] & 0xC0) >> 6
            tlen = cmd12[10] | (cmd12[11] << 8)
            print(f"  {label or cmd12.hex(' ')}  [type={ct} dlen={tlen}]")
            if not pkts:
                print("     <- (no response)")
            for ms, d in pkts:
                show = d.hex(' ')
                if len(show) > 200:
                    show = show[:200] + f" ... (+{len(d)-66} more)"
                print(f"     <- {ms:4d}ms  {len(d):5d}B  {show}")
        return pkts

    def release(self):
        try:
            usb.util.release_interface(self.dev, 0)
        except Exception:
            pass
        usb.util.dispose_resources(self.dev)


def init(r, verbose=True):
    if verbose:
        print(f"[init] device info: {r.ctrl().hex(' ')}")
    r.issue(cmd_bulk(b"\x05\x13", param=b"\x01\x00\x00\x00"), label="select_system(1)")
    r.issue(cmd_bulk(b"\x45\x0d", dlen=2), label="get_enroll_num")
    return r


def main():
    r = Rtk()
    op = sys.argv[1] if len(sys.argv) > 1 else "info"
    try:
        if op == "info":
            init(r)
        elif op == "addr":
            init(r, verbose=False)
            print("\n=== GET_TEMPLATE (45 0e) addr sweep, clean resync per command, dlen=35 ===")
            for a in (0, 35, 70, 105, 140, 175, 0x100, 0x200, 0x400):
                r.issue(cmd_bulk(b"\x45\x0e", addr=a, dlen=35),
                        label=f"get_template addr={a:#x} dlen=35")
        elif op == "param":
            init(r, verbose=False)
            print("\n=== GET_TEMPLATE (45 0e) param sweep, dlen=35 ===")
            for i in (0, 1, 2, 9, 10, 11, 15, 16, 255):
                r.issue(cmd_bulk(b"\x45\x0e", param=bytes([i, 0, 0, 0]), dlen=35),
                        label=f"get_template param0={i} dlen=35")
        elif op == "dlen":
            init(r, verbose=False)
            print("\n=== GET_TEMPLATE dlen sweep (addr=0, param=0) ===")
            for n in (35, 36, 64, 70, 128, 350):
                r.issue(cmd_bulk(b"\x45\x0e", dlen=n), label=f"get_template dlen={n}")
        elif op == "raw":
            init(r, verbose=False)
            data = bytes(int(x, 16) for x in sys.argv[2:])
            r.issue(data, label="raw")
    finally:
        r.release()


if __name__ == "__main__":
    sys.exit(main())
