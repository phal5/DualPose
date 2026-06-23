#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Seonghyeon Park
"""
t37_heatmap.py - Render heatmap images from logged maXTouch T37 capacitive
data (CSV produced by t37_reader.py --csv, or NPZ from --npz).

Each logged frame is an xSize x ySize matrix of int16 node values. This tool
turns those frames into PNG images, an animated GIF, a montage grid, or a
single averaged image.

Input formats:
  CSV : columns  t, iso, label, mode, xsize, ysize, n0..nN   (one row/frame)
        (older CSVs without the 'iso' column are also accepted)
  NPZ : arrays   data (N, xsize, ysize), t, label, mode

Usage examples:
  # one PNG per frame into out/
  python3 t37_heatmap.py capture.csv --frames-dir out

  # single frame (index 0) to a PNG
  python3 t37_heatmap.py capture.csv --frame 0 -o frame0.png

  # animated GIF of all frames
  python3 t37_heatmap.py capture.csv --gif capture.gif --fps 20

  # montage grid (e.g. every 10th frame) in one image
  python3 t37_heatmap.py capture.csv --montage montage.png --step 10

  # time-averaged heatmap
  python3 t37_heatmap.py capture.csv --mean mean.png

Requires: numpy, matplotlib    (pip install numpy matplotlib)
          pillow               (only for --gif:  pip install pillow)
"""

import argparse
import csv
import math
import os
import sys

try:
    import numpy as np
except ImportError:
    sys.exit("error: numpy not installed.  pip install numpy matplotlib")

import matplotlib
matplotlib.use("Agg")          # headless: write image files, no GUI window
import matplotlib.pyplot as plt

MODE_NAMES = {0x10: "deltas", 0x11: "refs"}


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #
class FrameSet:
    """grids: (N, xsize, ysize) int array; t/label/mode: length-N arrays."""
    def __init__(self, grids, t, label, mode):
        self.grids = grids
        self.t = t
        self.label = label
        self.mode = mode

    def __len__(self):
        return len(self.grids)


def load_csv(path):
    grids, t, label, mode = [], [], [], []
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {name: i for i, name in enumerate(header)}
        for col in ("xsize", "ysize"):
            if col not in idx:
                sys.exit("error: CSV missing '%s' column" % col)
        node_cols = [i for i, name in enumerate(header) if name.startswith("n")
                     and name[1:].isdigit()]
        node_cols.sort(key=lambda i: int(header[i][1:]))
        for row in r:
            if not row:
                continue
            xs = int(row[idx["xsize"]])
            ys = int(row[idx["ysize"]])
            vals = [int(row[c]) for c in node_cols[:xs * ys]]
            if len(vals) < xs * ys:
                continue
            grids.append(np.array(vals, dtype=np.int32).reshape(xs, ys))
            t.append(float(row[idx["t"]]) if "t" in idx else len(t))
            label.append(row[idx["label"]] if "label" in idx else "")
            mode.append(int(row[idx["mode"]]) if "mode" in idx else 0x10)
    if not grids:
        sys.exit("error: no frames parsed from %s" % path)
    return FrameSet(np.array(grids), np.array(t), np.array(label),
                    np.array(mode))


def load_npz(path):
    z = np.load(path, allow_pickle=True)
    grids = z["data"]
    n = len(grids)
    t = z["t"] if "t" in z else np.arange(n)
    label = z["label"] if "label" in z else np.array([""] * n)
    mode = z["mode"] if "mode" in z else np.array([0x10] * n)
    return FrameSet(grids, t, label, mode)


def load(path):
    if path.lower().endswith(".npz"):
        return load_npz(path)
    return load_csv(path)


# --------------------------------------------------------------------------- #
# Rendering helpers                                                            #
# --------------------------------------------------------------------------- #
def _clim(fs, args):
    """Return (vmin, vmax) for the color scale."""
    if args.vmin is not None and args.vmax is not None:
        return args.vmin, args.vmax
    if args.per_frame:
        return None, None                      # computed per frame
    return int(fs.grids.min()), int(fs.grids.max())   # global


def _draw(ax, grid, mode, vmin, vmax, cmap):
    # match t37_reader orientation: imshow(grid.T, origin lower)
    im = ax.imshow(grid.T, origin="lower", aspect="auto", cmap=cmap,
                   vmin=vmin, vmax=vmax)
    ax.set_xlabel("X channel")
    ax.set_ylabel("Y channel")
    return im


def _title(fs, i):
    return "%s  %dx%d  min=%d max=%d" % (
        MODE_NAMES.get(int(fs.mode[i]), hex(int(fs.mode[i]))),
        fs.grids[i].shape[0], fs.grids[i].shape[1],
        int(fs.grids[i].min()), int(fs.grids[i].max()))


# --------------------------------------------------------------------------- #
# Output modes                                                                 #
# --------------------------------------------------------------------------- #
def render_single(fs, i, out, args):
    vmin, vmax = _clim(fs, args)
    if args.per_frame:
        vmin, vmax = int(fs.grids[i].min()), int(fs.grids[i].max())
    fig, ax = plt.subplots(figsize=args.figsize)
    im = _draw(ax, fs.grids[i], fs.mode[i], vmin, vmax, args.cmap)
    fig.colorbar(im, ax=ax)
    lbl = str(fs.label[i]) if fs.label[i] else ""
    ax.set_title("frame %d  %s  %s" % (i, lbl, _title(fs, i)))
    fig.tight_layout()
    fig.savefig(out, dpi=args.dpi)
    plt.close(fig)
    return out


def render_frames_dir(fs, d, args):
    os.makedirs(d, exist_ok=True)
    width = max(4, len(str(len(fs) - 1)))
    written = 0
    for i in range(0, len(fs), args.step):
        out = os.path.join(d, "frame_%0*d.png" % (width, i))
        render_single(fs, i, out, args)
        written += 1
        if not args.quiet:
            print("\r%d images -> %s" % (written, d), end="", flush=True)
    if not args.quiet:
        print()
    return written


def render_montage(fs, out, args):
    idxs = list(range(0, len(fs), args.step))
    n = len(idxs)
    cols = args.cols or int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    vmin, vmax = _clim(fs, args)
    fig, axes = plt.subplots(rows, cols,
                             figsize=(cols * args.figsize[0],
                                      rows * args.figsize[1]))
    axes = np.atleast_1d(axes).ravel()
    last_im = None
    for ax, i in zip(axes, idxs):
        vlo, vhi = (int(fs.grids[i].min()), int(fs.grids[i].max())) \
            if args.per_frame else (vmin, vmax)
        last_im = ax.imshow(fs.grids[i].T, origin="lower", aspect="auto",
                            cmap=args.cmap, vmin=vlo, vmax=vhi)
        ax.set_title("%d" % i, fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
    for ax in axes[len(idxs):]:
        ax.axis("off")
    if last_im is not None and not args.per_frame:
        fig.colorbar(last_im, ax=axes.tolist(), shrink=0.6)
    fig.suptitle("T37 montage  %d frames (step %d)" % (n, args.step))
    fig.savefig(out, dpi=args.dpi)
    plt.close(fig)
    return out


def render_mean(fs, out, args):
    mean = fs.grids.mean(axis=0)
    fig, ax = plt.subplots(figsize=args.figsize)
    vmin, vmax = (args.vmin, args.vmax) if args.vmin is not None else \
        (mean.min(), mean.max())
    im = ax.imshow(mean.T, origin="lower", aspect="auto", cmap=args.cmap,
                   vmin=vmin, vmax=vmax)
    fig.colorbar(im, ax=ax)
    ax.set_xlabel("X channel"); ax.set_ylabel("Y channel")
    ax.set_title("T37 mean of %d frames" % len(fs))
    fig.tight_layout()
    fig.savefig(out, dpi=args.dpi)
    plt.close(fig)
    return out


def render_gif(fs, out, args):
    import matplotlib.animation as animation
    vmin, vmax = _clim(fs, args)
    if vmin is None:                           # per-frame disabled for gif scale
        vmin, vmax = int(fs.grids.min()), int(fs.grids.max())
    fig, ax = plt.subplots(figsize=args.figsize)
    im = ax.imshow(fs.grids[0].T, origin="lower", aspect="auto",
                   cmap=args.cmap, vmin=vmin, vmax=vmax)
    fig.colorbar(im, ax=ax)
    ax.set_xlabel("X channel"); ax.set_ylabel("Y channel")
    ttl = ax.set_title("")

    idxs = list(range(0, len(fs), args.step))

    def update(k):
        i = idxs[k]
        im.set_data(fs.grids[i].T)
        ttl.set_text("frame %d  %s" % (i, _title(fs, i)))
        return im, ttl

    anim = animation.FuncAnimation(fig, update, frames=len(idxs),
                                   interval=1000.0 / args.fps, blit=False)
    try:
        anim.save(out, writer="pillow", fps=args.fps)
    except Exception as e:
        plt.close(fig)
        sys.exit("error: GIF save failed (%s). Install pillow: pip install pillow"
                 % e)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# Multi-source (side-by-side) rendering                                        #
# --------------------------------------------------------------------------- #
def _multi_clim(fs_list, args):
    if args.vmin is not None and args.vmax is not None:
        return args.vmin, args.vmax
    if args.per_frame:
        return None, None
    lo = min(int(f.grids.min()) for f in fs_list)
    hi = max(int(f.grids.max()) for f in fs_list)
    return lo, hi


def render_multi_gif(fs_list, out, args, names=None):
    """Animated GIF with all sources side by side (1 row, P columns)."""
    import matplotlib.animation as animation
    p = len(fs_list)
    names = names or ["src%d" % i for i in range(p)]
    nframes = min(len(f) for f in fs_list)
    if nframes == 0:
        print("skip GIF: a source has 0 frames"); return None
    vmin, vmax = _multi_clim(fs_list, args)
    if vmin is None:
        vmin = min(int(f.grids.min()) for f in fs_list)
        vmax = max(int(f.grids.max()) for f in fs_list)
    fig, axes = plt.subplots(1, p,
                             figsize=(p * args.figsize[0], args.figsize[1]))
    axes = np.atleast_1d(axes).ravel()
    ims = []
    for ax, fs, nm in zip(axes, fs_list, names):
        im = ax.imshow(fs.grids[0].T, origin="lower", aspect="auto",
                       cmap=args.cmap, vmin=vmin, vmax=vmax)
        ax.set_title(nm); ax.set_xlabel("X"); ax.set_ylabel("Y")
        ims.append(im)
    fig.colorbar(ims[-1], ax=axes.tolist(), shrink=0.7)
    idxs = list(range(0, nframes, args.step))

    def update(k):
        i = idxs[k]
        for im, fs in zip(ims, fs_list):
            im.set_data(fs.grids[i].T)
        fig.suptitle("frame %d" % i)
        return ims

    anim = animation.FuncAnimation(fig, update, frames=len(idxs),
                                   interval=1000.0 / args.fps, blit=False)
    try:
        anim.save(out, writer="pillow", fps=args.fps)
    except Exception as e:
        plt.close(fig)
        sys.exit("error: GIF save failed (%s). pip install pillow" % e)
    plt.close(fig)
    return out


def render_multi_montage(fs_list, out, args, names=None):
    """Grid: rows = sampled time steps, cols = sources."""
    p = len(fs_list)
    names = names or ["src%d" % i for i in range(p)]
    nframes = min(len(f) for f in fs_list)
    idxs = list(range(0, nframes, args.step))
    rows = len(idxs)
    if rows == 0:
        print("skip montage: no frames"); return None
    vmin, vmax = _multi_clim(fs_list, args)
    fig, axes = plt.subplots(rows, p,
                             figsize=(p * args.figsize[0],
                                      rows * args.figsize[1]),
                             squeeze=False)
    last = None
    for r, i in enumerate(idxs):
        for c, fs in enumerate(fs_list):
            ax = axes[r][c]
            vlo, vhi = (int(fs.grids[i].min()), int(fs.grids[i].max())) \
                if args.per_frame else (vmin, vmax)
            last = ax.imshow(fs.grids[i].T, origin="lower", aspect="auto",
                            cmap=args.cmap, vmin=vlo, vmax=vhi)
            if r == 0:
                ax.set_title(names[c])
            if c == 0:
                ax.set_ylabel("f%d" % i, fontsize=8)
            ax.set_xticks([]); ax.set_yticks([])
    if last is not None and not args.per_frame:
        fig.colorbar(last, ax=axes.ravel().tolist(), shrink=0.6)
    fig.suptitle("T37 side-by-side  %d steps x %d sources" % (rows, p))
    fig.savefig(out, dpi=args.dpi)
    plt.close(fig)
    return out


def render_multi_mean(fs_list, out, args, names=None):
    """1 row, P columns of per-source time-averaged heatmaps."""
    p = len(fs_list)
    names = names or ["src%d" % i for i in range(p)]
    fig, axes = plt.subplots(1, p,
                             figsize=(p * args.figsize[0], args.figsize[1]),
                             squeeze=False)
    for c, fs in enumerate(fs_list):
        m = fs.grids.mean(axis=0)
        ax = axes[0][c]
        vmin, vmax = (args.vmin, args.vmax) if args.vmin is not None \
            else (m.min(), m.max())
        im = ax.imshow(m.T, origin="lower", aspect="auto", cmap=args.cmap,
                       vmin=vmin, vmax=vmax)
        ax.set_title("%s mean (%d)" % (names[c], len(fs)))
        ax.set_xlabel("X"); ax.set_ylabel("Y")
        fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout()
    fig.savefig(out, dpi=args.dpi)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Render heatmap images from logged T37 data (CSV/NPZ)")
    ap.add_argument("input", help="capture.csv or data.npz")
    # output modes (pick one; default = montage to t37_montage.png)
    ap.add_argument("-o", "--out", help="output path for --frame / default single")
    ap.add_argument("--frame", type=int, help="render a single frame by index")
    ap.add_argument("--frames-dir", metavar="DIR",
                    help="render every frame (see --step) as PNGs into DIR")
    ap.add_argument("--montage", metavar="PNG", help="grid montage image")
    ap.add_argument("--gif", metavar="GIF", help="animated GIF")
    ap.add_argument("--mean", metavar="PNG", help="time-averaged heatmap")
    # styling / selection
    ap.add_argument("--step", type=int, default=1,
                    help="use every Nth frame (default 1)")
    ap.add_argument("--cols", type=int, help="montage columns (default ~sqrt)")
    ap.add_argument("--cmap", default="viridis", help="matplotlib colormap")
    ap.add_argument("--vmin", type=int, help="fixed color-scale min")
    ap.add_argument("--vmax", type=int, help="fixed color-scale max")
    ap.add_argument("--per-frame", action="store_true",
                    help="autoscale color per frame instead of global")
    ap.add_argument("--fps", type=float, default=20.0, help="GIF frames/sec")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--figsize", type=float, nargs=2, default=(5.0, 4.0),
                    metavar=("W", "H"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    args.figsize = tuple(args.figsize)

    fs = load(args.input)
    if not args.quiet:
        print("loaded %d frames  (%dx%d)  from %s"
              % (len(fs), fs.grids[0].shape[0], fs.grids[0].shape[1],
                 args.input))

    did = False
    if args.frame is not None:
        out = args.out or "t37_frame_%d.png" % args.frame
        print("wrote", render_single(fs, args.frame, out, args)); did = True
    if args.frames_dir:
        n = render_frames_dir(fs, args.frames_dir, args)
        print("wrote %d PNGs -> %s" % (n, args.frames_dir)); did = True
    if args.montage:
        print("wrote", render_montage(fs, args.montage, args)); did = True
    if args.mean:
        print("wrote", render_mean(fs, args.mean, args)); did = True
    if args.gif:
        print("wrote", render_gif(fs, args.gif, args)); did = True

    if not did:                                # nothing requested -> montage
        out = args.out or "t37_montage.png"
        print("wrote", render_montage(fs, out, args))


if __name__ == "__main__":
    main()
