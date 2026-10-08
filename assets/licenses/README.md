# Included resources and historical license records

The 0.8.1 application includes only the Clef weight named by `../model.json`.
Qwen manifests and license texts remain as provenance records; their weights are not bundled and old Qwen execution is disabled.
The application does not download removed weights or substitute another model for a frozen Qwen run.

| Resource | Included content, license and provenance |
| --- | --- |
| Clef-Flash Q4_K_M | Current bundled weight; Apache-2.0; `Clef-LICENSE.txt`; Cloudflare decision model with joint schema head, ggml-org GGUF conversion; pinned revision and checksum in `../model.json` |
| Qwen3.5-4B Q4_K_M | Historical metadata and license only; no bundled weight; Apache-2.0; `Qwen3.5-LICENSE.txt`; Qwen source and Unsloth quantization records in `../generative-model.json` |
| Qwen3-0.6B Q8_0 | Historical metadata and license only; no bundled weight; Apache-2.0; `Qwen-LICENSE.txt`; revision and checksum record in `../legacy-model.json` |
| llama.cpp b11429 | Bundled runtime; MIT; `llama.cpp-LICENSE.txt`; upstream macOS arm64 release |
| NVIDIA Nemotron Personas Japan Viewer 10,000-row pool and frozen 53-row pack | Bundled data; CC BY 4.0; attribution and modification statement in `../data/ATTRIBUTION.md`; metadata in `../data/nemotron-japan-sample.json` and `../data/nemotron-japan-53.json` |
| Python.framework 3.12 | Bundled framework; supplied distribution license in Resources/English.lproj/License.rtf |
| MarkText/Muya fence parsing helpers | Bundled helpers and MIT notice; `MarkText-LICENSE.txt`; adapted from commit `0d8dba02bb77efdf33198a3b197bf8fdb42bec79` |

The build excludes every weight except the current manifest entry, even if other model files exist in the source folder.
It copies the Python framework's supplied license resources and excludes host site-packages.
The local application uses an ad-hoc signature and is not a notarized public release.
