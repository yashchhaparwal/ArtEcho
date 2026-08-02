"""
seed.py
=======
Loads the iconic-artwork library into the database.

The library itself lives in app/data/artworks.json. Every entry is in the PUBLIC
DOMAIN (artist died before 1955 and the work predates 1930), which is the
constraint the client set — works still under copyright, such as Dali's
'The Persistence of Memory', Hopper's 'Nighthawks' or Kahlo's self-portraits,
are deliberately excluded and are pruned from the database on re-seed.
"""

import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.models.artwork import ReferenceArtwork

DATA_FILE = Path(__file__).parent / "app" / "data" / "artworks.json"

# Works previously seeded that are NOT public domain. Removed on every run so a
# database seeded with an earlier version of this file becomes compliant.
NON_PUBLIC_DOMAIN = [
    ("The Persistence of Memory", "Salvador Dalí"),
    ("Nighthawks", "Edward Hopper"),
    ("Self-Portrait with Thorn Necklace and Hummingbird", "Frida Kahlo"),
]

SEEDABLE_FIELDS = {
    "title",
    "artist",
    "year",
    "movement_style",
    "medium",
    "description",
    "source_attribution",
    "image_url",
    "dominant_color",
    "is_public_domain",
}


def load_library() -> list[dict]:
    if not DATA_FILE.exists():
        raise SystemExit(
            f"Artwork library not found at {DATA_FILE}.\n"
            f"It ships with the repository — restore it from version control."
        )
    with DATA_FILE.open(encoding="utf-8") as handle:
        records = json.load(handle)
    return [{k: v for k, v in record.items() if k in SEEDABLE_FIELDS} for record in records]


def remove_stale_library_rows(db, library: list[dict]) -> int:
    """
    Drop library rows that no longer appear in artworks.json — e.g. an entry
    that was renamed, leaving the old title behind as a duplicate.

    User uploads are never touched, and neither is a row some session still
    references, since deleting it would orphan that conversation.
    """
    from app.models.session import SessionReference

    keep = {(record["title"], record["artist"]) for record in library}
    removed = 0
    rows = (
        db.query(ReferenceArtwork)
        .filter(ReferenceArtwork.is_custom_upload == False)  # noqa: E712
        .all()
    )
    for row in rows:
        if (row.title, row.artist) in keep:
            continue
        in_use = (
            db.query(SessionReference)
            .filter(SessionReference.reference_artwork_id == row.id)
            .count()
        )
        if in_use:
            print(f"  ! Kept stale entry still used by {in_use} session(s): '{row.title}'")
            continue
        db.delete(row)
        print(f"  - Removed stale entry: '{row.title}' by {row.artist}")
        removed += 1
    return removed


def remove_non_public_domain(db) -> int:
    """Delete copyrighted works left over from an earlier seed."""
    removed = 0
    for title, artist in NON_PUBLIC_DOMAIN:
        rows = (
            db.query(ReferenceArtwork)
            .filter(
                ReferenceArtwork.title == title,
                ReferenceArtwork.artist == artist,
                ReferenceArtwork.is_custom_upload == False,  # noqa: E712
            )
            .all()
        )
        for row in rows:
            db.delete(row)
            print(f"  - Removed (not public domain): '{title}' by {artist}")
            removed += 1
    return removed


def seed_data():
    artworks = load_library()
    db = SessionLocal()
    try:
        print(f"Seeding {len(artworks)} iconic public-domain artworks...")
        removed = remove_non_public_domain(db)
        removed += remove_stale_library_rows(db, artworks)

        created, updated, unchanged = 0, 0, 0
        for artwork_data in artworks:
            existing = (
                db.query(ReferenceArtwork)
                .filter(
                    ReferenceArtwork.title == artwork_data["title"],
                    ReferenceArtwork.artist == artwork_data["artist"],
                )
                .first()
            )
            if not existing:
                db.add(ReferenceArtwork(**artwork_data))
                print(f"  + Added: '{artwork_data['title']}' by {artwork_data['artist']}")
                created += 1
                continue

            # Refresh mutable metadata so corrections here reach already-seeded
            # rows. A changed image_url invalidates the cached vision analysis,
            # which describes the old picture.
            changed = [
                field
                for field, value in artwork_data.items()
                if getattr(existing, field) != value
            ]
            if not changed:
                unchanged += 1
                continue

            for field in changed:
                setattr(existing, field, artwork_data[field])
            if "image_url" in changed:
                existing.visual_analysis = None
            print(f"  ~ Updated: '{artwork_data['title']}' ({', '.join(changed)})")
            updated += 1

        db.commit()
        print(
            f"\nSeeding complete! {created} created, {updated} updated, "
            f"{unchanged} unchanged, {removed} removed."
        )
        total = (
            db.query(ReferenceArtwork)
            .filter(ReferenceArtwork.is_custom_upload == False)  # noqa: E712
            .count()
        )
        print(f"Library now holds {total} public-domain artworks.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
