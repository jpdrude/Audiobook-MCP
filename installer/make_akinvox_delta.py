"""Convert the AkinVox German adapter into a patch for the official Kokoro v1.0 ONNX model.  (maintainer tool)

AkinVox's German voices (https://huggingface.co/AKinvox/kokoro-multispeaker, Apache-2.0) are not a separate model:
they are low-rank (LoRA) corrections for 201 weight tensors of the stock Kokoro-82M weights, plus a bank of voice
style vectors. The official Kokoro v1.0 ONNX model (the English model this project already installs) holds the same
weights, so the German model is  English ONNX + patch.  This script finds every target tensor inside the ONNX by
value, expresses each correction in the ONNX layout (transposed Linear weights, re-ordered LSTM gates) and writes

    akinvox-de-delta.npz    low-rank factors + metadata (about 70 MB)
    akinvox-de-voices.npz   the 8 German voices as style tensors (510, 1, 256) for kokoro-onnx

Needs torch (CPU build is enough), numpy and onnx; end users only need patch_akinvox.py.

  make_akinvox_delta.py --base kokoro-v1_0.pth --adapter adapter.pt --onnx kokoro-v1.0.onnx --out OUTDIR
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

EXPECTED = {   # pinned inputs; the script refuses anything else
    "base_pth": "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",   # hexgrad/Kokoro-82M f3ff357
    "adapter": "2c6ddf215bfabfcce16efb54fcdaaead4b4dbe4285054b27764c6cfe9b137834",     # AKinvox de, revision 2b3fa45
    "onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",        # kokoro-v1.0.onnx (kokoro-onnx v1.0)
}
UNUSED_TARGETS = {("bert", "pooler", "weight")}   # ALBERT pooler: not part of Kokoro's graph, cannot affect output


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    import onnx
    import torch
    from onnx import numpy_helper

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for key, path in (("base_pth", a.base), ("adapter", a.adapter), ("onnx", a.onnx)):
        got = sha256(path)
        if got != EXPECTED[key]:
            sys.exit(f"{key}: sha256 {got} is not the pinned {EXPECTED[key]}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rel = torch.load(a.adapter, map_location="cpu", weights_only=True, mmap=True)
    base = torch.load(a.base, map_location="cpu", weights_only=True)
    targets, state = rel["targets"], rel["state"]
    assert len(targets) == 201 and len(state) == 402

    model = onnx.load(a.onnx, load_external_data=False)
    index = collections.defaultdict(list)           # element count -> [(initializer, lstm_direction, array)]
    for init in model.graph.initializer:
        arr = numpy_helper.to_array(init)
        if arr.dtype != np.float32 or arr.size < 3:
            continue
        index[arr.size].append((init.name, None, arr))
        if arr.ndim == 3 and arr.shape[0] in (1, 2):
            for d in range(arr.shape[0]):
                index[arr[d].size].append((init.name, d, arr[d]))

    def stock(t):
        sd = base[t["root"]]
        pre = "module." + (t["module"] + "." if t["module"] else "")
        if pre + t["parameter"] in sd:
            return sd[pre + t["parameter"]].float().numpy()
        g, v = sd[pre + "weight_g"].float(), sd[pre + "weight_v"].float()      # fold weight norm like the exporter
        return (v * (g / v.norm(dim=tuple(range(1, v.ndim)), keepdim=True))).numpy()

    def lstm_rows(x):                      # PyTorch gate order i,f,g,o  ->  ONNX LSTM order i,o,f,g
        h = x.shape[0] // 4
        return np.concatenate([x[0:h], x[3 * h:4 * h], x[h:2 * h], x[2 * h:3 * h]], axis=0)

    def close(x, y):
        return x.shape == y.shape and float(np.max(np.abs(x - y))) <= 1e-5 * max(1.0, float(np.max(np.abs(y))))

    entries, arrays, skipped = [], {}, []
    for n, t in enumerate(targets):
        w = stock(t)
        is_lstm = t["parameter"].startswith(("weight_ih", "weight_hh"))
        variants = [("lstm", lstm_rows(w))] if is_lstm else [("id", w)] + ([("T", np.ascontiguousarray(w.T))] if w.ndim == 2 else [])
        hits = [(name, d, kind) for kind, y in variants for name, d, x in index.get(y.size, []) if close(x, y)]
        if not hits and (t["root"], t["module"], t["parameter"]) in UNUSED_TARGETS:
            skipped.append(f'{t["root"]}.{t["module"]}.{t["parameter"]}')
            continue
        if len(hits) != 1:
            sys.exit(f'target {n} {t["root"]}.{t["module"]}.{t["parameter"]}: {len(hits)} matches in the ONNX model (need exactly 1)')
        name, d, kind = hits[0]
        A, B = state[t["prefix"] + ".A"].float().numpy(), state[t["prefix"] + ".B"].float().numpy()
        # delta (PyTorch layout) = (B @ A).reshape(shape) * alpha / rank ; express it in the ONNX layout as B' @ A'
        if kind == "T":
            A2, B2 = np.ascontiguousarray(B.T), np.ascontiguousarray(A.T)     # (B@A).T = A.T @ B.T
        elif kind == "lstm":
            A2, B2 = A, lstm_rows(B)                                          # row permutation only touches B
        else:
            A2, B2 = A, B
        k = len(entries)
        arrays[f"A{k}"], arrays[f"B{k}"] = A2.astype(np.float32), B2.astype(np.float32)
        entries.append({"init": name, "dir": d, "kind": kind, "scale": float(t["alpha"]) / A.shape[0],
                        "target": f'{t["root"]}.{t["module"]}.{t["parameter"]}'})

    meta = {"format": "akinvox-de-delta/v1", "onnx_sha256": EXPECTED["onnx"], "base_sha256": EXPECTED["base_pth"],
            "adapter_sha256": EXPECTED["adapter"], "entries": entries, "skipped_unused": skipped,
            "source": "https://huggingface.co/AKinvox/kokoro-multispeaker (Apache-2.0), revision 2b3fa45b39256382872823562da36d371a808e5a"}
    np.savez(out / "akinvox-de-delta.npz", meta=np.array(json.dumps(meta)), **arrays)

    bank = rel["voicebank"].float().numpy()
    voices = {name.replace("AV_", ""): np.ascontiguousarray(bank[i][:, None, :]) for i, name in enumerate(rel["speaker_names"])}
    np.savez(out / "akinvox-de-voices.npz", **voices)
    print(f"{len(entries)} corrections written (skipped, unused by the graph: {skipped})")
    print("voices:", list(voices), {k: v.shape for k, v in list(voices.items())[:1]})
    for f in ("akinvox-de-delta.npz", "akinvox-de-voices.npz"):
        print(f"  {f}  {(out / f).stat().st_size / 1e6:.1f} MB  sha256 {sha256(out / f)}")


if __name__ == "__main__":
    main()
