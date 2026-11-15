"""Turn the installed English Kokoro ONNX model into the AkinVox German model by applying the converted patch.

  patch_akinvox.py kokoro-v1.0.onnx akinvox-de-delta.npz kokoro-de-akinvox.onnx

Only numpy and onnx are needed (no PyTorch). The patch file is made by make_akinvox_delta.py. The input model must be
exactly the official Kokoro v1.0 ONNX (its SHA-256 is checked); the output is the same graph with 200 weight tensors
updated:  W' = W + scale * (B @ A).
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def apply(src, delta, dst):
    import onnx
    from onnx import numpy_helper

    z = np.load(delta, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    if meta.get("format") != "akinvox-de-delta/v1":
        raise SystemExit("not an AkinVox delta file")
    got = sha256(src)
    if got != meta["onnx_sha256"]:
        raise SystemExit(f"{src} is not the official Kokoro v1.0 ONNX model (sha256 {got})")
    model = onnx.load(str(src))
    inits = {i.name: i for i in model.graph.initializer}
    touched = set()
    for k, e in enumerate(meta["entries"]):
        init = inits[e["init"]]
        arr = numpy_helper.to_array(init).copy()
        delta_w = (z[f"B{k}"] @ z[f"A{k}"]) * e["scale"]
        if e["dir"] is None:
            arr += delta_w.reshape(arr.shape).astype(arr.dtype)
        else:
            arr[e["dir"]] += delta_w.reshape(arr[e["dir"]].shape).astype(arr.dtype)
        key = (e["init"], e["dir"])
        if key in touched:
            raise SystemExit(f"tensor patched twice: {key}")
        touched.add(key)
        init.CopyFrom(numpy_helper.from_array(arr, init.name))
    tmp = Path(str(dst) + ".part")
    onnx.save(model, str(tmp))
    tmp.replace(dst)
    print(f"patched {len(meta['entries'])} tensors -> {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    apply(*sys.argv[1:])
