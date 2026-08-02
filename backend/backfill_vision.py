"""
backfill_vision.py
==================
Pre-computes the vision analysis for every library artwork.

Analysis is cached on the artwork row, so this only ever needs to run once per
image — but running it up front means a user's first conversation about a given
artwork starts instantly instead of waiting on CPU inference.

Expect roughly 20-40 seconds per artwork on CPU, so a full library pass takes a
while. It is safe to interrupt and re-run: finished artworks are skipped.

Usage:
    python backfill_vision.py            # analyse everything not yet done
    python backfill_vision.py --force    # re-analyse everything
    python backfill_vision.py --limit 10 # do a first batch only
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.models.artwork import ReferenceArtwork
from app.services.artwork_analysis import analyze_artwork_by_id
from app.services.vision_provider import vision_service


def main():
    parser = argparse.ArgumentParser(description="Backfill vision analysis for artworks.")
    parser.add_argument("--force", action="store_true", help="re-analyse artworks that already have an analysis")
    parser.add_argument("--limit", type=int, default=0, help="stop after N artworks")
    args = parser.parse_args()

    if not vision_service.is_available():
        raise SystemExit(
            f"Vision model '{vision_service.model}' is not installed in Ollama.\n"
            f"Install it first:  ollama pull {vision_service.model.split(':')[0]}\n"
            f"(or set OLLAMA_VISION_MODEL in .env to a model you already have)"
        )

    with SessionLocal() as db:
        query = db.query(ReferenceArtwork.id, ReferenceArtwork.title)
        if not args.force:
            query = query.filter(ReferenceArtwork.visual_analysis.is_(None))
        targets = query.order_by(ReferenceArtwork.created_at.asc()).all()

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("Nothing to do — every artwork already has a vision analysis.")
        return

    print(f"Analysing {len(targets)} artwork(s) with '{vision_service.model}'...\n")
    succeeded = failed = 0
    started = time.perf_counter()

    for index, (artwork_id, title) in enumerate(targets, start=1):
        label = title.encode("ascii", "replace").decode("ascii")
        turn = time.perf_counter()
        try:
            result = analyze_artwork_by_id(artwork_id, force=args.force)
        except Exception as exc:
            result, exc_note = None, str(exc)
        else:
            exc_note = ""

        elapsed = time.perf_counter() - turn
        if result:
            succeeded += 1
            print(f"[{index}/{len(targets)}] OK   {label} ({elapsed:.1f}s)")
        else:
            failed += 1
            print(f"[{index}/{len(targets)}] FAIL {label} ({elapsed:.1f}s) {exc_note}")

    total = time.perf_counter() - started
    print(f"\nDone in {total / 60:.1f} min — {succeeded} analysed, {failed} failed.")
    if failed:
        print("Failed artworks keep working from their catalogue metadata; re-run to retry.")


if __name__ == "__main__":
    main()
