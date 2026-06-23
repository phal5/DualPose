#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Seonghyeon Park
"""
t37_to_h5.py - Convert captured maXTouch T37 CSV log(s) into an HDF5 (.h5)
dataset ready for ML training (e.g. Keras / PyTorch).

Input: one or more CSV files produced by t37_reader.py --csv. Columns:
    t, iso, [port,] label, mode, xsize, ysize, n0..nN

Output .h5 layout (flat, default):
    /X        float32  (N, xsize, ysize)   capacitive node values
    /y        int64    (N,)                 integer class id
    /t        float64  (N,)                 host timestamp (epoch s)
    /port     int8     (N,)                 source port index (0 if absent)
    /mode     int8     (N,)                 T37 mode (0x10 deltas / 0x11 refs)
    attrs: classes(list[str]), xsize, ysize, count, normalized(bool)

With --val-split P (0<P<1): writes two groups instead, /train/* and /val/*,
each with the same arrays. Split is stratified per class and shuffled.

Examples:
    # single file, label taken from the CSV's 'label' column
    python3 t37_to_h5.py fist.csv -o dataset.h5

    # combine several files; override each file's label by filename
    python3 t37_to_h5.py fist.csv open.csv peace.csv -o hands.h5

    # force one label for a file (overrides the CSV column)
    python3 t37_to_h5.py raw.csv:fist more.csv:open -o hands.h5

    # z-score normalize, 20% validation split
    python3 t37_to_h5.py *.csv -o hands.h5 --normalize --val-split 0.2

    # keep only one port's frames from a dual-port capture
    python3 t37_to_h5.py dual.csv -o p0.h5 --only-port 0

Requires: numpy, h5py    (pip install numpy h5py)
"""

import argparse
import csv
import sys

try:
    import numpy as np
except ImportError:
    sys.exit("error: numpy not installed.  pip install numpy h5py")
try:
    import h5py
except ImportError:
    sys.exit("error: h5py not installed.  pip install h5py")


# --------------------------------------------------------------------------- #
def parse_input_spec(spec):
    """'file.csv' or 'file.csv:label' -> (path, forced_label or None)."""
    # only split on the LAST ':' and avoid Windows drive letters (C:\...)
    if ":" in spec[2:]:
        path, _, lbl = spec.rpartition(":")
        if path and lbl:
            return path, lbl
    return spec, None


def load_csv(path, forced_label, only_port):
    """Return list of dicts: grid(np xsize,ysize), label, t, port, mode."""
    out = []
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {name: i for i, name in enumerate(header)}
        for col in ("xsize", "ysize"):
            if col not in idx:
                sys.exit("error: %s missing '%s' column" % (path, col))
        node_cols = sorted((i for i, n in enumerate(header)
                            if n.startswith("n") and n[1:].isdigit()),
                           key=lambda i: int(header[i][1:]))
        has_port = "port" in idx
        for row in r:
            if not row:
                continue
            port = int(row[idx["port"]]) if has_port else 0
            if only_port is not None and port != only_port:
                continue
            xs = int(row[idx["xsize"]]); ys = int(row[idx["ysize"]])
            vals = [int(row[c]) for c in node_cols[:xs * ys]]
            if len(vals) < xs * ys:
                continue
            label = forced_label if forced_label is not None else \
                (row[idx["label"]] if "label" in idx else "")
            out.append(dict(
                grid=np.array(vals, dtype=np.float32).reshape(xs, ys),
                label=label,
                t=float(row[idx["t"]]) if "t" in idx else float(len(out)),
                port=port,
                mode=int(row[idx["mode"]]) if "mode" in idx else 0x10,
            ))
    return out


def build_arrays(samples):
    grids = np.stack([s["grid"] for s in samples])          # (N, xs, ys)
    t = np.array([s["t"] for s in samples], dtype=np.float64)
    port = np.array([s["port"] for s in samples], dtype=np.int8)
    mode = np.array([s["mode"] for s in samples], dtype=np.int8)
    labels = [s["label"] for s in samples]
    classes = sorted(set(labels))
    cls_to_id = {c: i for i, c in enumerate(classes)}
    y = np.array([cls_to_id[l] for l in labels], dtype=np.int64)
    return grids, y, t, port, mode, classes


def write_group(g, X, y, t, port, mode):
    g.create_dataset("X", data=X, compression="gzip")
    g.create_dataset("y", data=y, compression="gzip")
    g.create_dataset("t", data=t, compression="gzip")
    g.create_dataset("port", data=port, compression="gzip")
    g.create_dataset("mode", data=mode, compression="gzip")


def main():
    ap = argparse.ArgumentParser(
        description="Convert T37 CSV capture(s) into an .h5 ML dataset")
    ap.add_argument("inputs", nargs="+",
                    help="CSV file(s), optionally 'file.csv:label' to force a label")
    ap.add_argument("-o", "--out", required=True, help="output .h5 path")
    ap.add_argument("--normalize", action="store_true",
                    help="z-score normalize X (per dataset, using train stats)")
    ap.add_argument("--val-split", type=float, default=0.0,
                    help="fraction for validation group (0..1); 0 = flat dataset")
    ap.add_argument("--only-port", type=int,
                    help="keep only this port index (for dual-port captures)")
    ap.add_argument("--seed", type=int, default=0, help="shuffle seed")
    args = ap.parse_args()

    samples = []
    for spec in args.inputs:
        path, lbl = parse_input_spec(spec)
        s = load_csv(path, lbl, args.only_port)
        print("loaded %5d frames from %s%s"
              % (len(s), path, "  (label=%s)" % lbl if lbl else ""))
        samples.extend(s)

    if not samples:
        sys.exit("error: no frames loaded")

    X, y, t, port, mode, classes = build_arrays(samples)
    n = len(X)
    print("total %d frames  shape %s  classes=%s"
          % (n, X.shape[1:], classes))
    counts = {c: int((y == i).sum()) for i, c in enumerate(classes)}
    print("class counts:", counts)

    # shuffle
    rng = np.random.default_rng(args.seed)
    perm = rng.permutation(n)
    X, y, t, port, mode = X[perm], y[perm], t[perm], port[perm], mode[perm]

    # split indices (stratified per class)
    val_idx = np.zeros(n, dtype=bool)
    if 0.0 < args.val_split < 1.0:
        for i in range(len(classes)):
            ci = np.where(y == i)[0]
            k = int(round(len(ci) * args.val_split))
            val_idx[ci[:k]] = True

    # normalization (fit on training portion only)
    norm = {}
    if args.normalize:
        fit = X[~val_idx] if val_idx.any() else X
        mu = float(fit.mean()); sd = float(fit.std()) or 1.0
        X = (X - mu) / sd
        norm = dict(mean=mu, std=sd)
        print("normalized: mean=%.3f std=%.3f" % (mu, sd))

    with h5py.File(args.out, "w") as h:
        h.attrs["classes"] = np.array(classes, dtype=h5py.string_dtype())
        h.attrs["xsize"] = X.shape[1]
        h.attrs["ysize"] = X.shape[2]
        h.attrs["count"] = n
        h.attrs["normalized"] = bool(args.normalize)
        if norm:
            h.attrs["norm_mean"] = norm["mean"]
            h.attrs["norm_std"] = norm["std"]

        if val_idx.any():
            tr = ~val_idx
            write_group(h.create_group("train"),
                        X[tr], y[tr], t[tr], port[tr], mode[tr])
            write_group(h.create_group("val"),
                        X[val_idx], y[val_idx], t[val_idx], port[val_idx],
                        mode[val_idx])
            print("wrote train=%d  val=%d -> %s"
                  % (int(tr.sum()), int(val_idx.sum()), args.out))
        else:
            write_group(h, X, y, t, port, mode)
            print("wrote %d samples -> %s" % (n, args.out))

    print("classes (id -> name): "
          + ", ".join("%d=%s" % (i, c) for i, c in enumerate(classes)))


if __name__ == "__main__":
    main()
