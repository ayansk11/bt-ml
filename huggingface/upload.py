"""Upload the A1 model + label dataset to HuggingFace.

DOES NOT hardcode a token. Reads HF_TOKEN from the environment.
Usage:

    export HF_TOKEN=hf_...       # Your HF access token
    .venv/bin/python huggingface/upload.py                    # uploads both repos
    .venv/bin/python huggingface/upload.py --model-only       # only model repo
    .venv/bin/python huggingface/upload.py --dataset-only     # only dataset repo
    .venv/bin/python huggingface/upload.py --owner <username> # override owner
    .venv/bin/python huggingface/upload.py --dry-run          # print plan only

Never commit this file with your token inlined.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"
HF_DIR = ROOT / "huggingface"

DEFAULT_OWNER = "Ayansk11"
MODEL_REPO_NAME = "bt-eta-correction-a1"
DATASET_REPO_NAME = "bt-gtfs-rt-labels-2026-04-18"


def _require_token() -> str:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        sys.stderr.write("ERROR: HF_TOKEN env var not set. Run `export HF_TOKEN=hf_...` first.\n")
        sys.exit(2)
    return token


def _check_paths(paths: list[Path]) -> None:
    missing = [p for p in paths if not p.exists()]
    if missing:
        sys.stderr.write("ERROR: missing required files:\n  " + "\n  ".join(str(p) for p in missing) + "\n")
        sys.exit(2)


def upload_model(owner: str, token: str, dry_run: bool) -> None:
    repo_id = f"{owner}/{MODEL_REPO_NAME}"
    model_files = {
        MODEL_DIR / "a1_delay_correction.joblib": "a1_delay_correction.joblib",
        MODEL_DIR / "a1_metadata.json": "a1_metadata.json",
        MODEL_DIR / "route_intercepts.json": "route_intercepts.json",
        HF_DIR / "model_card.md": "README.md",
    }
    _check_paths(list(model_files.keys()))
    print(f"[upload] MODEL repo -> {repo_id}")
    for src, dst in model_files.items():
        size_kb = src.stat().st_size / 1024
        print(f"  upload {src.relative_to(ROOT)} -> {dst}  ({size_kb:.1f} KB)")
    if dry_run:
        print("  (dry-run - no upload)")
        return

    from huggingface_hub import HfApi, create_repo
    api = HfApi(token=token)
    create_repo(repo_id, repo_type="model", exist_ok=True, token=token)
    for src, dst in model_files.items():
        api.upload_file(
            path_or_fileobj=str(src),
            path_in_repo=dst,
            repo_id=repo_id,
            repo_type="model",
        )
    print(f"[upload] MODEL done -> https://huggingface.co/{repo_id}")


def upload_dataset(owner: str, token: str, dry_run: bool) -> None:
    repo_id = f"{owner}/{DATASET_REPO_NAME}"
    data_files = {
        DATA_DIR / "ground_truth_arrivals.parquet": "data/ground_truth_arrivals.parquet",
        DATA_DIR / "ground_truth_trip_exclusions.parquet": "data/ground_truth_trip_exclusions.parquet",
        DATA_DIR / "bt_prediction_error.parquet": "data/bt_prediction_error.parquet",
        DATA_DIR / "ground_truth_coverage.md": "coverage.md",
        HF_DIR / "dataset_card.md": "README.md",
    }
    _check_paths(list(data_files.keys()))
    print(f"[upload] DATASET repo -> {repo_id}")
    for src, dst in data_files.items():
        size_kb = src.stat().st_size / 1024
        print(f"  upload {src.relative_to(ROOT)} -> {dst}  ({size_kb:.1f} KB)")
    if dry_run:
        print("  (dry-run - no upload)")
        return

    from huggingface_hub import HfApi, create_repo
    api = HfApi(token=token)
    create_repo(repo_id, repo_type="dataset", exist_ok=True, token=token)
    for src, dst in data_files.items():
        api.upload_file(
            path_or_fileobj=str(src),
            path_in_repo=dst,
            repo_id=repo_id,
            repo_type="dataset",
        )
    print(f"[upload] DATASET done -> https://huggingface.co/datasets/{repo_id}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--owner", default=DEFAULT_OWNER)
    p.add_argument("--model-only", action="store_true")
    p.add_argument("--dataset-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    token = "" if args.dry_run else _require_token()

    if not args.dataset_only:
        upload_model(args.owner, token, args.dry_run)
    if not args.model_only:
        upload_dataset(args.owner, token, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
