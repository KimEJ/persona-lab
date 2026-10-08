# Local verification artifacts

Detailed local reports, persona raw inputs, process/PID records and generated receipts are not uploaded. The measured results and limitations are summarized in `docs/VERIFICATION.md`, `docs/PARQUET.md` and `docs/MODEL.md`.

`julia-requirements.txt` pins the optional isolated CPU environment. Running explicitly selected smoke/verification tools creates new ignored artifacts here. Core Mock tests need only the project-authored synthetic fixture and do not download data or models.
