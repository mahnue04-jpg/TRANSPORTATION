# Nova Voice: approved local narration checkpoint

Owner approved the real local greeting pronunciation and then the full commercial narration in chat on November 1, 2026. This approval covers the reviewed pronunciation and audio delivery. It does not establish a cloned presenter voice, completed Studio integration, or approval of future generated audio.

## Completed

- Original 30-second commercial imported into Studio project `cproj_b2f02eb88e8c`; playback, download byte equality and persistence after reload verified. Video soundtrack was not replaced with the new narration.
- Local greeting generated with actual Kokoro weights: 4.05 seconds.
- Full approved script generated locally: 28.0 seconds of speech plus 2.0 seconds of silence in a 30-second WAV; MP3 saved separately as `Nova_Local_Full_Commercial_Narration_30s_APPROVED.mp3`.
- Model: `hexgrad/Kokoro-82M`, revision `f3ff3571791e39611d31c381e3a41a3af07b4987`.
- Model SHA-256: `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4`.
- Stock voice: `af_heart`; Kokoro 0.9.4, PyTorch 2.6.0+cpu, Python 3.12, 24 kHz mono PCM.
- Full narration synthesis speed: 0.87; no clipped samples. Peak process RAM observed around 1775 MiB.
- No paid provider calls. Python socket connections blocked during inference; no connection attempts observed in the generation harness. This is application-level isolation, not an OS network sandbox.
- Updated the audio-only pronunciation mapping to the reviewed Kokoro sequence `[AMICOR](/ˈɑmɪkɔɹ/)`; written script and captions retain their spelling. Both GetAmiCore.com and getamicor.com use the approved spoken brand.
- 23 offline contract checks passed locally. The modified adapter also generated a real 4.05-second greeting with preloaded model/voice files and no paid fallback.

## Next implementation milestone

Connect this adapter to an explicitly selected Nova local voice provider in an isolated Studio test environment. Keep existing provider selection intact. Enforce CPU/RAM admission and one inference at a time; the measured runtime is too large to assume it fits the existing production service. Preserve the approved video and narration, and validate owner-scoped save/play/download before proposing production changes.

The approved full commercial was generated with a standalone local harness. The repository demo runner still generates its short greeting only. Full-script input, speed/timing controls, model provisioning, dependency pinning, background execution and Studio storage integration remain implementation work. Do not describe the local provider as production-ready.

Older research/runbook documents describe the pre-acquisition state; this checkpoint supersedes their “not run” status for the experiments above only.
