# Third-party notices

Audiobook-MCP itself is MIT licensed (see `LICENSE`). The German voices use third-party model data.

## AkinVox Kokoro Multispeaker (German voices)

- Source: https://huggingface.co/AKinvox/kokoro-multispeaker, licensed under the Apache License 2.0
  (https://www.apache.org/licenses/LICENSE-2.0).
- NOTICE of the original: "AkinVox Kokoro Multispeaker. Copyright 2026 AkinVox contributors. This product includes
  modified native inference code derived from Kokoro and StyleTTS2 (MIT License, Aaron (Yinghao) Li)."
- **Modifications made here:** the German adapter (`adapters/de/adapter.pt`, low-rank weight updates) and the voice
  bank were converted into two files, `akinvox-de-delta.npz` (weight patch for the official Kokoro v1.0 ONNX model)
  and `akinvox-de-voices.npz` (voice style vectors for eight voices), with `installer/make_akinvox_delta.py`.
  `installer/patch_akinvox.py` applies the patch to the ONNX model on the user's computer. Nothing else of the
  original is changed.

## Kokoro-82M

Apache License 2.0, https://huggingface.co/hexgrad/Kokoro-82M, and the ONNX export and `kokoro-onnx` package by
thewh1teagle (MIT), https://github.com/thewh1teagle/kokoro-onnx. Downloaded at install time, not redistributed here.

## Voice data sources named by AkinVox

No recordings are distributed. The voice styles were trained by AkinVox on these datasets:

- **Thorsten**: Thorsten-Voice, Thorsten Müller and Dominik Kreutz, CC0.
- **Bernd, Eva K, Karlsson, Hokuspokus, Julia**: HUI-Audio-Corpus-German (Puchtler, Wirth, Peinl; IISYS, Hof
  University), derived from LibriVox recordings, CC0.
- **Kerstin**: Rhasspy German dataset, CC0.
- **Mucky**: Muckylixx/mucky-voice-final, **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/). Credit:
  Muckylixx. The voice data was converted into a style vector by AkinVox and by the conversion described above;
  those are changes. If you publish audio made with this voice, credit "Mucky (Muckylixx), CC BY 4.0".

## Other components

- eSpeak-NG (GPL-3.0), used through the `espeakng-loader` / `phonemizer` packages installed by pip, not included in
  this repository.
- wordfreq (Apache-2.0 code; data under CC BY-SA 4.0), ONNX Runtime (MIT), ffmpeg (downloaded, LGPL/GPL build by
  gyan.dev), MCP Python SDK (MIT).

The voices are AI-generated speech. Label audio you publish accordingly.
