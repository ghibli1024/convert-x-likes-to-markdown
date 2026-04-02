#!/usr/bin/env python3
"""
Reclassify an existing X Likes archive using manual taxonomy rules.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict

import sync_x_likes as sync


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reclassify an existing X Likes archive from its current notes.")
    parser.add_argument("--archive-root", required=True, help="Existing X Likes archive root")
    parser.add_argument("--taxonomy-reference-md", help="Optional taxonomy markdown path to copy into the archive before reclassification")
    parser.add_argument("--backup-root", help="Optional backup destination; defaults to a sibling timestamped backup")
    return parser.parse_args()


def timestamp_suffix() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def default_backup_root(archive_root: Path) -> Path:
    return archive_root.parent / f"{archive_root.name}.backup-{timestamp_suffix()}"


def backup_archive(archive_root: Path, backup_root: Path) -> None:
    if backup_root.exists():
        raise FileExistsError(f"backup destination already exists: {backup_root}")
    subprocess.run(
        ["cp", "-R", str(archive_root), str(backup_root)],
        check=True,
    )


def validate_archive_root(archive_root: Path) -> None:
    required = [
        archive_root / sync.root_date_name(),
        archive_root / sync.root_author_name(),
        archive_root / sync.root_domain_name(),
        archive_root / sync.dashboard_name(),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"archive root is missing required paths: {', '.join(missing)}")


def reclassify_x_likes_archive(
    archive_root: Path,
    taxonomy_reference_md: Path | None = None,
    backup_root: Path | None = None,
) -> Dict[str, object]:
    archive_root = archive_root.expanduser().resolve()
    validate_archive_root(archive_root)
    sync.set_active_language(sync.detect_archive_language(archive_root))

    resolved_backup_root = backup_root.expanduser().resolve() if backup_root else default_backup_root(archive_root)
    backup_archive(archive_root, resolved_backup_root)

    explicit_rules_path = None
    if taxonomy_reference_md is not None:
        explicit_rules_path = taxonomy_reference_md.expanduser().resolve()
        if not explicit_rules_path.exists():
            raise FileNotFoundError(f"taxonomy reference not found: {explicit_rules_path}")

    manual_rules_path = explicit_rules_path or sync.resolve_manual_rules_path(archive_root, None)
    manual_rules = sync.load_manual_rules(manual_rules_path)

    records: Dict[str, sync.Record] = {}
    for date_root in sync.existing_date_roots(archive_root):
        records.update(sync.parse_existing_records(date_root))
    rubbish_ids = sync.collect_rubbish_tweet_ids(archive_root)
    sync.apply_rubbish_filter(records, rubbish_ids)
    sync.reclassify_records_manual(records, manual_rules)
    sync.rebalance_domains(records, max_size=sync.MAX_DOMAIN_FILE_SIZE, max_depth=sync.MAX_DOMAIN_DEPTH)

    stage_parent = Path(tempfile.mkdtemp(prefix="xlikes-reclassify-"))
    stage_root = stage_parent / archive_root.name
    stage_root.mkdir(parents=True, exist_ok=True)
    try:
        render_result = sync.render_structure(stage_root, records)
        sync.replace_target(archive_root, stage_root)
        sync.ensure_local_root_taxonomy(archive_root, manual_rules_path, manual_rules)
        sync.normalize_date_tree(archive_root / sync.root_date_name())
        sync.normalize_domain_tree(archive_root / sync.root_domain_name())
        sync.cleanup_empty_duplicate_dirs(archive_root / sync.root_date_name())
        sync.cleanup_empty_duplicate_dirs(archive_root / sync.root_domain_name())
        md_count, tweet_count = sync.validate_output(archive_root, len(records))
        summary = {
            "archive_root": str(archive_root),
            "taxonomy_reference_md": str(manual_rules_path),
            "classification": "manual",
            "source_mode": "taxonomy-reclassify",
            "backup_root": str(resolved_backup_root),
            "rubbish_removed": len(rubbish_ids),
            "final_notes": len(records),
            "final_tweet_notes": tweet_count,
            "final_md_files_under_date": md_count,
            "top_domains": render_result["top_domains"],
            "top_domain_count": render_result["top_domain_count"],
            "month_stats": render_result["month_items"],
            "url_count": render_result["url_count"],
            "max_domain_leaf_size": render_result["max_domain_leaf_size"],
            "max_domain_depth": render_result["max_domain_depth"],
            "oversized_leaf_count": render_result["oversized_leaf_count"],
        }
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    args = parse_args()
    reclassify_x_likes_archive(
        archive_root=Path(args.archive_root),
        taxonomy_reference_md=Path(args.taxonomy_reference_md) if args.taxonomy_reference_md else None,
        backup_root=Path(args.backup_root) if args.backup_root else None,
    )


if __name__ == "__main__":
    main()
