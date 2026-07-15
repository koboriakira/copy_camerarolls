#!/usr/bin/env python3
"""
NAS → S3 incremental sync (Glacier Deep Archive).

Wraps `aws s3 sync` to replicate the NAS photo archive to S3 as a
disaster-recovery copy. Objects are uploaded directly as DEEP_ARCHIVE
to minimise cost.

Usage:
    python3 s3_sync.py                          # default source & bucket
    python3 s3_sync.py --dry-run                # plan only
    python3 s3_sync.py --source /Volumes/photo  # custom NAS mount
    python3 s3_sync.py --bucket other-bucket    # custom bucket
"""

import argparse
import subprocess
import sys

DEFAULT_SOURCE = "/Volumes/photo"
DEFAULT_BUCKET = "koboriakira-photo-archive"
AWS_PROFILE = "AdministratorAccess-743218050155"
STORAGE_CLASS = "DEEP_ARCHIVE"


def run_sync(source: str, bucket: str, dry_run: bool) -> int:
    cmd = [
        "aws", "s3", "sync",
        source,
        f"s3://{bucket}/photos/",
        "--storage-class", STORAGE_CLASS,
        "--profile", AWS_PROFILE,
        "--exclude", ".*",
        "--exclude", "*.DS_Store",
    ]
    if dry_run:
        cmd.append("--dryrun")

    print(f"{'[DRY RUN] ' if dry_run else ''}NAS → S3 sync")
    print(f"  source:  {source}")
    print(f"  dest:    s3://{bucket}/photos/")
    print(f"  class:   {STORAGE_CLASS}")
    print()

    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(description="NAS → S3 photo archive sync")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="NAS mount path")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="S3 bucket name")
    parser.add_argument("--dry-run", action="store_true", help="plan only, no upload")
    args = parser.parse_args()

    if not __import__("pathlib").Path(args.source).exists():
        print(f"Error: {args.source} が見つかりません。NAS はマウントされていますか？", file=sys.stderr)
        sys.exit(1)

    rc = run_sync(args.source, args.bucket, args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
