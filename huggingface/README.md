# HuggingFace push - instructions

This is run manually by the maintainer. Requires a personal `HF_TOKEN` (write-scoped).

## One-time: install the CLI + SDK

Already covered by the workspace venv - `huggingface_hub` is a transitive dep of `transformers` and should already be importable. If not:

```bash
cd /Users/ayansk11/Desktop/bt-ml
.venv/bin/pip install --quiet huggingface_hub
```

## Each time you want to push

```bash
cd /Users/ayansk11/Desktop/bt-ml

# 1. Revoke the old token you pasted into chat earlier.
#    Go to https://huggingface.co/settings/tokens → delete it.

# 2. Generate a fresh token scoped to 'write' at:
#    https://huggingface.co/settings/tokens
export HF_TOKEN=hf_your_new_token_here   # NEVER commit this

# 3. Dry-run first to see exactly what will be uploaded
.venv/bin/python huggingface/upload.py --dry-run

# 4. Push for real
.venv/bin/python huggingface/upload.py

# Or push just one side
.venv/bin/python huggingface/upload.py --model-only
.venv/bin/python huggingface/upload.py --dataset-only
```

## What gets pushed

### Model repo `Ayansk11/bt-eta-correction-a1`
- `a1_delay_correction.joblib` - trained LightGBM
- `a1_metadata.json` - CV metrics, feature importance, training-sample counts
- `route_intercepts.json` - A2 per-route intercept table
- `README.md` - contents of `huggingface/model_card.md`

### Dataset repo `Ayansk11/bt-gtfs-rt-labels-2026-04-18`
- `data/ground_truth_arrivals.parquet` - 994 labelled (trip, stop) pairs
- `data/ground_truth_trip_exclusions.parquet` - excluded trips
- `data/bt_prediction_error.parquet` - 28,658 BT predictions scored
- `coverage.md` - narrative coverage report
- `README.md` - contents of `huggingface/dataset_card.md`

## What does NOT get pushed (and should never)

- `.venv/`
- `data/gtfs_static/*.txt` (agency-provided; consult ETA Transit Systems for redistribution)
- Raw `.pb` protobuf snapshots (`gtfs_logs/*.pb` in the sibling data workspace)
- `.env`, `HF_TOKEN`, any API key

`bt-ml/.gitignore` and `huggingface/upload.py`'s explicit file-list protect against accidental inclusion.
