#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Seonghyeon Park
"""
t37_reader.py - Host-side reader for the maXTouch T37 capacitive raw-data
stream emitted by the PIC32MZ EF Legato quick-start firmware over UART6.

Wire protocol (binary, little-endian), one frame per capacitive scan:

    offset  field            bytes  notes
    ------  ---------------  -----  -------------------------------------------
      0     sync0 = 0xAA       1
      1     sync1 = 0x55       1
      2     mode               1     0x10 = deltas, 0x11 = references
      3     xSize              1     matrix X channels
      4     ySize              1     matrix Y channels
      5     nodeCount          2     uint16, == xSize * ySize
      7     payload   nodeCount*2    int16 per node, node k -> x=k//ySize, y=k%ySize
      ...   checksum           2     uint16 = sum of all payload bytes (mod 65536)

Usage examples:
    python3 t37_reader.py --port /dev/tty.usbserial-XXXX
    python3 t37_reader.py --port COM5 --plot
    python3 t37_reader.py --port /dev/ttyUSB0 --csv capture.csv --label fist
    python3 t37_reader.py --port /dev/ttyUSB0 --npz dataset.npz --label open_hand

Requires: pyserial            (pip install pyserial)
Optional: numpy, matplotlib   (for --plot live heatmap and --npz dataset)
"""

import argparse
import csv
import datetime
import os
import sys
import threading
import time

# allow importing the sibling t37_heatmap.py for combined data+image capture
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def ntp_offset(server="pool.ntp.org", timeout=3.0):
    """Query an NTP server once. Returns (offset_seconds, server_unixtime)
       where offset = server_time - local_time, or (None, None) on failure.
       No external deps - minimal SNTP over UDP."""
    import socket
    import struct
    NTP_DELTA = 2208988800            # 1900->1970 epoch difference
    pkt = b"\x1b" + 47 * b"\0"        # LI=0, VN=3, Mode=3 (client)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.time()
        s.sendto(pkt, (server, 123))
        data, _ = s.recvfrom(48)
        t3 = time.time()
    except Exception:
        return None, None
    finally:
        s.close()
    secs = struct.unpack("!12I", data)[10]      # transmit timestamp (seconds)
    frac = struct.unpack("!12I", data)[11]
    server_unix = (secs - NTP_DELTA) + frac / 2.0 ** 32
    offset = server_unix - (t0 + t3) / 2.0
    return offset, server_unix


def net_cols(frame_t, args):
    """Return [net_epoch, net_utc_iso] using the NTP offset captured at start.
       Falls back to local time (offset 0) when NTP was unavailable."""
    off = getattr(args, "net_offset", None) or 0.0
    nt = frame_t + off
    iso = datetime.datetime.fromtimestamp(
        nt, datetime.timezone.utc).isoformat(timespec="milliseconds")
    return ["%.4f" % nt, iso]


def default_logdir():
    """<GCC>/t37_logs  - walk up from this script to the 'GCC' ancestor."""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.basename(d) == "GCC":
            return os.path.join(d, "t37_logs")
        parent = os.path.dirname(d)
        if parent == d:                         # reached fs root, fall back
            return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "t37_logs")
        d = parent


_OUTPUT_ATTRS = ("csv", "npz", "gif", "montage", "mean", "frames_dir")


def resolve_outputs(args):
    """Put relative output files under <outdir>/[run_TIMESTAMP]/.
       Absolute paths are left untouched. Returns the run dir (or None)."""
    if not any(getattr(args, a) for a in _OUTPUT_ATTRS):
        return None
    base = args.outdir or default_logdir()
    if not args.no_session:
        base = os.path.join(base, "run_" +
                            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(base, exist_ok=True)
    for a in _OUTPUT_ATTRS:
        v = getattr(args, a)
        if v and not os.path.isabs(v):
            setattr(args, a, os.path.join(base, v))
    print("saving outputs to: %s" % base)
    return base

try:
    import serial  # pyserial
except ImportError:
    sys.exit("error: pyserial not installed. Run:  pip install pyserial")

SYNC0 = 0xAA
SYNC1 = 0x55
HDR_LEN = 7
MODE_NAMES = {0x10: "deltas", 0x11: "refs"}


class Frame:
    __slots__ = ("mode", "xsize", "ysize", "nodes", "t")

    def __init__(self, mode, xsize, ysize, nodes, t):
        self.mode = mode
        self.xsize = xsize
        self.ysize = ysize
        self.nodes = nodes          # list[int], length xsize*ysize
        self.t = t                  # host timestamp (s)

    def grid(self):
        """Return nodes as rows[x][y] (matrix order k = x*ysize + y)."""
        ys = self.ysize
        return [self.nodes[x * ys:(x + 1) * ys] for x in range(self.xsize)]


def _read_exact(ser, n):
    """Read exactly n bytes or return None on timeout/short read."""
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_frame(ser):
    """Block until one valid, checksum-verified frame is parsed. Returns Frame
    or None on serial timeout. Bogus headers / bad checksums just re-sync in
    this loop -- never via recursion (a noisy stream used to recurse until
    RecursionError and crash the reader)."""
    while True:
        # Resynchronise on the 0xAA 0x55 marker.
        state = 0
        while True:
            b = ser.read(1)
            if not b:
                return None
            byte = b[0]
            if state == 0:
                state = 1 if byte == SYNC0 else 0
            elif state == 1:
                if byte == SYNC1:
                    break
                state = 1 if byte == SYNC0 else 0

        rest = _read_exact(ser, HDR_LEN - 2)    # mode,x,y,countLo,countHi
        if rest is None:
            return None
        mode, xsize, ysize, cnt_lo, cnt_hi = rest
        node_count = cnt_lo | (cnt_hi << 8)

        if node_count == 0 or node_count > 4096:
            continue                            # bogus header, resync

        payload = _read_exact(ser, node_count * 2)
        if payload is None:
            return None
        chk = _read_exact(ser, 2)
        if chk is None:
            return None

        calc = sum(payload) & 0xFFFF
        recv = chk[0] | (chk[1] << 8)
        if calc != recv:
            continue                            # corrupt frame, resync

        nodes = [int.from_bytes(payload[i:i + 2], "little", signed=True)
                 for i in range(0, len(payload), 2)]
        return Frame(mode, xsize, ysize, nodes, time.time())


# --------------------------------------------------------------------------- #
# Terminal heat map (no third-party deps)                                     #
# --------------------------------------------------------------------------- #
_RAMP = " .:-=+*#%@"


def print_nums(frame, width=5):
    """Print the node grid as a numeric table (rows = X, cols = Y)."""
    nodes = frame.nodes
    lo = min(nodes)
    hi = max(nodes)
    sys.stdout.write("\x1b[H\x1b[2J")           # home + clear
    print("mode=%s  matrix=%dx%d  nodes=%d  min=%d max=%d"
          % (MODE_NAMES.get(frame.mode, hex(frame.mode)),
             frame.xsize, frame.ysize, len(nodes), lo, hi))
    # Column header (Y index)
    print("     " + "".join("%*d" % (width, y) for y in range(frame.ysize)))
    for x, row in enumerate(frame.grid()):
        line = "".join("%*d" % (width, v) for v in row)
        print("%3d |%s" % (x, line))
    sys.stdout.flush()


def print_nums_multi(frames, names, width=4):
    """Print several ports' latest frames as numeric grids, stacked."""
    sys.stdout.write("\x1b[H\x1b[2J")           # home + clear
    for fr, nm in zip(frames, names):
        if fr is None:
            print("== %s ==  (waiting...)\n" % nm)
            continue
        nodes = fr.nodes
        print("== %s ==  %dx%d  min=%d max=%d"
              % (nm, fr.xsize, fr.ysize, min(nodes), max(nodes)))
        print("    " + "".join("%*d" % (width, y) for y in range(fr.ysize)))
        for x, row in enumerate(fr.grid()):
            print("%3d|%s" % (x, "".join("%*d" % (width, v) for v in row)))
        print()
    sys.stdout.flush()


def print_ascii(frame):
    nodes = frame.nodes
    lo = min(nodes)
    hi = max(nodes)
    span = (hi - lo) or 1
    sys.stdout.write("\x1b[H\x1b[2J")           # home + clear
    print("mode=%s  matrix=%dx%d  nodes=%d  min=%d max=%d"
          % (MODE_NAMES.get(frame.mode, hex(frame.mode)),
             frame.xsize, frame.ysize, len(nodes), lo, hi))
    for row in frame.grid():
        line = "".join(_RAMP[int((v - lo) * (len(_RAMP) - 1) / span)]
                       for v in row)
        print(line)
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Live matplotlib heat map                                                     #
# --------------------------------------------------------------------------- #
def run_plot(ser, args):
    import numpy as np
    import matplotlib.pyplot as plt

    first = None
    while first is None:
        first = read_frame(ser)
    img = np.array(first.grid())

    plt.ion()
    fig, ax = plt.subplots()
    im = ax.imshow(img.T, origin="lower", aspect="auto", cmap="viridis")
    fig.colorbar(im, ax=ax)
    ax.set_xlabel("X channel")
    ax.set_ylabel("Y channel")

    try:
        while plt.fignum_exists(fig.number):
            frame = read_frame(ser)
            if frame is None:
                continue
            grid = np.array(frame.grid())
            im.set_data(grid.T)
            im.set_clim(grid.min(), grid.max())
            ax.set_title("T37 %s  %dx%d  min=%d max=%d"
                         % (MODE_NAMES.get(frame.mode, hex(frame.mode)),
                            frame.xsize, frame.ysize,
                            int(grid.min()), int(grid.max())))
            plt.pause(0.001)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- #
# Capture / logging modes                                                      #
# --------------------------------------------------------------------------- #
def _wants_heatmap(args):
    return bool(args.gif or args.montage or args.mean or args.frames_dir)


def run_capture(ser, args):
    """Capture once; write CSV and/or NPZ and/or heatmap image(s) together."""
    rows = []                       # raw node rows (for CSV)
    grids, labels, modes, times = [], [], [], []
    n = 0
    csv_f = csv_w = None
    header_written = False
    try:
        if args.csv:
            csv_f = open(args.csv, "w", newline="")
            csv_w = csv.writer(csv_f)
        try:
            while args.count == 0 or n < args.count:
                frame = read_frame(ser)
                if frame is None:
                    continue

                if csv_w is not None:
                    if not header_written:
                        cols = (["t", "iso", "net_t", "net_utc", "label",
                                 "mode", "xsize", "ysize"]
                                + ["n%d" % i for i in range(len(frame.nodes))])
                        csv_w.writerow(cols)
                        header_written = True
                    iso = datetime.datetime.fromtimestamp(frame.t).isoformat(
                        timespec="milliseconds")
                    csv_w.writerow(["%.4f" % frame.t, iso]
                                   + net_cols(frame.t, args)
                                   + [args.label, frame.mode, frame.xsize,
                                      frame.ysize] + frame.nodes)

                # keep frames in memory for NPZ / heatmap
                if args.npz or _wants_heatmap(args):
                    grids.append(frame.grid())
                    labels.append(args.label)
                    modes.append(frame.mode)
                    times.append(frame.t)

                n += 1
                if args.nums:
                    print_nums(frame)
                    print("captured %d frames" % n)
                elif not args.quiet:
                    print("\rcaptured %d frames" % n, end="", flush=True)
        except KeyboardInterrupt:
            pass
    finally:
        if csv_f is not None:
            csv_f.close()

    if not args.quiet:
        print()
    if args.csv:
        print("wrote %d frames -> %s" % (n, args.csv))

    if n == 0:
        print("no frames captured; nothing else to write")
        return

    import numpy as np
    if args.npz:
        np.savez_compressed(args.npz,
                            data=np.array(grids, dtype=np.int16),
                            label=np.array(labels),
                            mode=np.array(modes),
                            t=np.array(times))
        print("wrote %d frames -> %s  (data shape %s)"
              % (n, args.npz, np.array(grids).shape))

    if _wants_heatmap(args):
        _render_heatmaps(np.array(grids, dtype=np.int32),
                         np.array(times), np.array(labels),
                         np.array(modes), args)


def _heatmap_namespace(args):
    return argparse.Namespace(
        step=args.step, cols=args.cols, cmap=args.cmap,
        vmin=args.vmin, vmax=args.vmax, per_frame=args.per_frame,
        fps=args.fps, dpi=args.dpi, figsize=tuple(args.figsize),
        quiet=args.quiet, out=None)


def write_aligned_csv(base, per_port, args):
    """Two free-running boards never capture at the same instant, so pair each
    port-0 frame with the nearest port-1 frame on the shared host clock and emit
    one wide, time-aligned row (with the actual skew in dt_ms). This is the
    ML-ready merge; the interleaved per-frame CSV stays as the raw log."""
    import os, bisect
    if len(per_port) < 2:
        return
    p0, p1 = per_port[0], per_port[1]
    t0s, t1s = p0["times"], p1["times"]
    if not t0s or not t1s:
        return
    # Tolerance = ~one port-0 frame period (reject pairs further apart).
    if len(t0s) > 1:
        dd = sorted(t0s[i + 1] - t0s[i] for i in range(len(t0s) - 1))
        tol = dd[len(dd) // 2]
    else:
        tol = 0.06
    n0 = [[v for row in g for v in row] for g in p0["grids"]]
    n1 = [[v for row in g for v in row] for g in p1["grids"]]
    stem, ext = os.path.splitext(base)
    out = stem + "_aligned" + (ext or ".csv")
    paired = 0
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t0", "t1", "dt_ms", "label"]
                   + ["a%d" % i for i in range(len(n0[0]) if n0 else 0)]
                   + ["b%d" % i for i in range(len(n1[0]) if n1 else 0)])
        for i, t in enumerate(t0s):
            j = bisect.bisect_left(t1s, t)
            cand = [k for k in (j - 1, j) if 0 <= k < len(t1s)]
            if not cand:
                continue
            k = min(cand, key=lambda k: abs(t1s[k] - t))
            dt = t1s[k] - t
            if abs(dt) > tol:
                continue                       # no port-1 frame close enough
            w.writerow(["%.4f" % t, "%.4f" % t1s[k], "%.1f" % (dt * 1000.0),
                        args.label] + n0[i] + n1[k])
            paired += 1
    print("aligned %d/%d frame pairs (tol %.0f ms, median skew shown per row) "
          "-> %s" % (paired, len(t0s), tol * 1000.0, out))


def run_capture_multi(ports, args):
    """Read 2+ ports concurrently. Merged CSV (with 'port' column) +
       side-by-side heatmap images."""
    sers = []
    for p in ports:
        try:
            s = serial.Serial(p, args.baud, timeout=1)
            time.sleep(0.2); s.reset_input_buffer()
            sers.append(s)
        except Exception as e:
            for s in sers:
                s.close()
            sys.exit("error: cannot open %s (%s)" % (p, e))
    print("opened %d ports @ %d baud: %s" % (len(sers), args.baud,
                                             ", ".join(ports)))

    lock = threading.Lock()
    stop = threading.Event()
    counts = [0] * len(sers)
    latest = [None] * len(sers)
    per_port = [dict(grids=[], times=[], labels=[], modes=[])
                for _ in sers]

    csv_f = csv_w = None
    header = {"written": False}
    if args.csv:
        csv_f = open(args.csv, "w", newline="")
        csv_w = csv.writer(csv_f)

    def worker(pi):
        ser = sers[pi]
        while not stop.is_set():
            try:
                frame = read_frame(ser)
            except serial.SerialException as e:
                print("\n[port%d] 연결 끊김: %s" % (pi, e), flush=True)
                stop.set()
                return
            if frame is None:
                continue
            with lock:
                if csv_w is not None:
                    if not header["written"]:
                        cols = (["t", "iso", "net_t", "net_utc", "port",
                                 "label", "mode", "xsize", "ysize"]
                                + ["n%d" % i for i in range(len(frame.nodes))])
                        csv_w.writerow(cols)
                        header["written"] = True
                    iso = datetime.datetime.fromtimestamp(frame.t).isoformat(
                        timespec="milliseconds")
                    csv_w.writerow(["%.4f" % frame.t, iso]
                                   + net_cols(frame.t, args)
                                   + [pi, args.label, frame.mode,
                                      frame.xsize, frame.ysize] + frame.nodes)
                d = per_port[pi]
                d["grids"].append(frame.grid())
                d["times"].append(frame.t)
                d["labels"].append(args.label)
                d["modes"].append(frame.mode)
                latest[pi] = frame
                counts[pi] += 1
            if args.count and counts[pi] >= args.count:
                return

    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(len(sers))]
    for t in threads:
        t.start()

    try:
        names_live = ["port%d" % i for i in range(len(sers))]
        # --quiet still emits a periodic health line so a silent/frozen board
        # (port open but no frames -- e.g. firmware I2C wedge) is visible.
        last_counts = list(counts)
        last_check = time.time()
        HEALTH_S = 2.0
        while any(t.is_alive() for t in threads):
            if args.count and all(c >= args.count for c in counts):
                break
            if args.nums:
                with lock:
                    snap = list(latest)
                print_nums_multi(snap, names_live)
                print("  ".join("p%d=%d" % (i, counts[i])
                                for i in range(len(sers))))
            elif not args.quiet:
                print("\r" + "  ".join("p%d=%d" % (i, counts[i])
                                       for i in range(len(sers))),
                      end="", flush=True)
            else:
                now = time.time()
                if now - last_check >= HEALTH_S:
                    parts = []
                    for i in range(len(sers)):
                        d = counts[i] - last_counts[i]
                        parts.append("p%d=%s" % (
                            i, "%.0fHz" % (d / (now - last_check))
                            if d > 0 else "STALL!"))
                    print("[%s] %s" % (
                        datetime.datetime.now().strftime("%H:%M:%S"),
                        "  ".join(parts)), flush=True)
                    last_counts = list(counts)
                    last_check = now
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)
        for s in sers:
            s.close()
        if csv_f is not None:
            csv_f.close()
        if args.csv and len(sers) >= 2:
            write_aligned_csv(args.csv, per_port, args)

    if not args.quiet:
        print()
    if args.csv:
        print("wrote merged CSV (%s) -> %s"
              % ("+".join("p%d=%d" % (i, counts[i])
                          for i in range(len(sers))), args.csv))

    import numpy as np
    fs_list, names = [], []
    import importlib
    hm = importlib.import_module("t37_heatmap")
    for i, d in enumerate(per_port):
        if not d["grids"]:
            print("port %d: 0 frames" % i); continue
        fs_list.append(hm.FrameSet(np.array(d["grids"], dtype=np.int32),
                                   np.array(d["times"]),
                                   np.array(d["labels"]),
                                   np.array(d["modes"])))
        names.append("port%d" % i)

    if args.npz:
        np.savez_compressed(
            args.npz,
            **{("data_p%d" % i): fs.grids for i, fs in enumerate(fs_list)},
            **{("t_p%d" % i): fs.t for i, fs in enumerate(fs_list)})
        print("wrote NPZ -> %s" % args.npz)

    if _wants_heatmap(args) and len(fs_list) >= 1:
        hargs = _heatmap_namespace(args)
        if args.montage:
            print("wrote", hm.render_multi_montage(fs_list, args.montage,
                                                   hargs, names))
        if args.mean:
            print("wrote", hm.render_multi_mean(fs_list, args.mean,
                                                hargs, names))
        if args.gif:
            print("wrote", hm.render_multi_gif(fs_list, args.gif,
                                               hargs, names))
        if args.frames_dir:
            print("note: --frames-dir not supported for multi-port; "
                  "use --montage/--gif")


def _render_heatmaps(grids, times, labels, modes, args):
    """Build images from in-memory frames using t37_heatmap's renderers."""
    import importlib
    hm = importlib.import_module("t37_heatmap")
    fs = hm.FrameSet(grids, times, labels, modes)

    # adapt reader args to the namespace t37_heatmap renderers expect
    hargs = argparse.Namespace(
        step=args.step, cols=args.cols, cmap=args.cmap,
        vmin=args.vmin, vmax=args.vmax, per_frame=args.per_frame,
        fps=args.fps, dpi=args.dpi, figsize=tuple(args.figsize),
        quiet=args.quiet, out=None)

    if args.frames_dir:
        cnt = hm.render_frames_dir(fs, args.frames_dir, hargs)
        print("wrote %d PNGs -> %s" % (cnt, args.frames_dir))
    if args.montage:
        print("wrote", hm.render_montage(fs, args.montage, hargs))
    if args.mean:
        print("wrote", hm.render_mean(fs, args.mean, hargs))
    if args.gif:
        print("wrote", hm.render_gif(fs, args.gif, hargs))


def run_print(ser, args):
    render = print_nums if args.nums else print_ascii
    try:
        while True:
            frame = read_frame(ser)
            if frame is None:
                continue
            render(frame)
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description="maXTouch T37 raw-data reader")
    ap.add_argument("--port", required=True, nargs="+",
                    help="serial port(s). One = normal; two+ = concurrent "
                         "capture -> merged CSV (port column) + side-by-side "
                         "heatmap. e.g. --port /dev/cu.usbmodemA /dev/cu.usbmodemB")
    ap.add_argument("--baud", type=int, default=460800, help="baud (def 460800)")
    ap.add_argument("--plot", action="store_true", help="live matplotlib heatmap")
    ap.add_argument("--nums", action="store_true",
                    help="terminal display as a numeric grid instead of ASCII heatmap")
    ap.add_argument("--csv", metavar="FILE", help="log frames to CSV")
    ap.add_argument("--npz", metavar="FILE", help="log frames to compressed .npz")
    ap.add_argument("--outdir", metavar="DIR",
                    help="base dir for relative output files "
                         "(default <GCC>/t37_logs)")
    ap.add_argument("--no-session", action="store_true",
                    help="save directly in --outdir, no run_TIMESTAMP subfolder")
    ap.add_argument("--ntp-server", default="pool.ntp.org",
                    help="NTP server for internet-time columns (net_t/net_utc)")
    ap.add_argument("--no-ntp", action="store_true",
                    help="skip NTP; net_t/net_utc fall back to local clock")
    # heatmap images written from the same capture (combine freely with --csv/--npz)
    hg = ap.add_argument_group("heatmap image output (saved alongside the log)")
    hg.add_argument("--gif", metavar="GIF", help="animated GIF of the capture")
    hg.add_argument("--montage", metavar="PNG", help="grid montage image")
    hg.add_argument("--mean", metavar="PNG", help="time-averaged heatmap")
    hg.add_argument("--frames-dir", metavar="DIR", help="one PNG per frame into DIR")
    hg.add_argument("--cols", type=int, help="montage columns (default ~sqrt)")
    hg.add_argument("--cmap", default="viridis", help="matplotlib colormap")
    hg.add_argument("--vmin", type=int, help="fixed color-scale min")
    hg.add_argument("--vmax", type=int, help="fixed color-scale max")
    hg.add_argument("--per-frame", action="store_true",
                    help="autoscale color per frame instead of global")
    hg.add_argument("--fps", type=float, default=20.0, help="GIF frames/sec")
    hg.add_argument("--dpi", type=int, default=110)
    hg.add_argument("--figsize", type=float, nargs=2, default=(5.0, 4.0),
                    metavar=("W", "H"))
    hg.add_argument("--step", type=int, default=1,
                    help="use every Nth frame for images")
    ap.add_argument("--label", default="", help="label tag stored with captures")
    ap.add_argument("--count", type=int, default=0,
                    help="stop after N frames (0 = run until Ctrl-C)")
    ap.add_argument("--quiet", action="store_true", help="suppress progress")
    args = ap.parse_args()

    # NTP sync once at startup -> internet-time columns (net_t / net_utc)
    args.net_offset = None
    if not args.no_ntp:
        off, srv = ntp_offset(args.ntp_server)
        if off is None:
            print("NTP: %s unreachable; net_* will use local clock"
                  % args.ntp_server)
        else:
            args.net_offset = off
            print("NTP %s: offset %+.3f s (local clock vs internet)"
                  % (args.ntp_server, off))

    resolve_outputs(args)            # route relative outputs to <GCC>/t37_logs

    # Two or more ports -> concurrent capture (merged CSV + side-by-side images)
    if len(args.port) > 1:
        if args.plot:
            print("note: --plot ignored in multi-port mode (use --nums for live)")
        if not (args.csv or args.npz or _wants_heatmap(args) or args.nums):
            sys.exit("multi-port mode needs --nums (live) or an output: "
                     "--csv/--npz/--gif/--montage/--mean")
        run_capture_multi(args.port, args)
        return

    port = args.port[0]
    print(f"Opening serial port {port} at {args.baud} baud...")
    ser = serial.Serial(port, args.baud, timeout=1)
    # Give the link a moment and flush any partial frame.
    time.sleep(0.2)
    ser.reset_input_buffer()
    print("Serial port opened successfully. Waiting for T37 frames...")

    try:
        if args.csv or args.npz or _wants_heatmap(args):
            run_capture(ser, args)         # data log and/or heatmap images
        elif args.plot:
            run_plot(ser, args)
        else:
            run_print(ser, args)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
