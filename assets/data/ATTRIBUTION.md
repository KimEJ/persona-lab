# Bundled persona data

NVIDIA; Fujita, Gong, Ogushi, Yamamoto, Suhara, Corneil and Meyer (2025), Nemotron-Personas-Japan: Synthetic Personas Aligned to Real-World Distributions

https://huggingface.co/datasets/nvidia/Nemotron-Personas-Japan

License: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/

## Current bundled pool

`nemotron-japan-pool-10000.jsonl` contains 10,000 distinct synthetic personas from the official public Hugging Face Dataset Viewer, `default` configuration, `train` split, row indices 0–9,999. The active metadata is `nemotron-japan-sample.json`.

Each complete returned row object was converted to UTF-8 JSONL without changing field values. Responses with truncated cells are rejected. One UUID is one person; six narratives are views of that person. The pool is a contiguous Viewer prefix, not a random or representative sample of all one million source personas. Random selection in the app operates within this bundled pool.

The Viewer rows API reads mutable `main`. Metadata records the local JSONL SHA-256 and the separately observed repository revision; it does not claim that the API response is bound to that revision. Retrieval time, page URLs and response hashes are recorded in `verification/persona-pool.json`.

Official API: https://datasets-server.huggingface.co/rows?dataset=nvidia%2FNemotron-Personas-Japan&config=default&split=train&offset=0&length=100

Recreate the bounded pool with `python3 tools/prepare_persona_pool.py`. The preparation tool uses the Python standard library and does not add an application dependency. A later retrieval from mutable `main` can produce a different local hash.

## Preserved legacy pool

`nemotron-japan-sample.jsonl` remains the original 53 public Viewer rows, byte for byte. This small frozen source is included in Git so the preparation tool can verify its legacy input in a new checkout. The 10,000-row pool is prepared separately and is not included in Git. The 53-row sample's original metadata is retained in `nemotron-japan-53.json` for frozen experiments. It was converted to JSONL without changing row values and is also not random or representative.

Legacy JSONL SHA-256: `826d6afc3b33ada62445f3fe5bb0db38dce7719a32d826f9758018e4a35fbcb2`.
