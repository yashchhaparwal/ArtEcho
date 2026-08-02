"""Live OpenAI chat test: opening message + one conversation turn."""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEURISTIC_MARKER = "Welcome to Muse! I'm thrilled you chose"

from app.services.llm_provider import llm_service

artwork = [
    {
        "title": "The Starry Night",
        "artist": "Vincent van Gogh",
        "year": 1889,
        "medium": "Oil on canvas",
        "movement_style": "Post-Impressionism",
    }
]


def main():
    if not llm_service.openai_api_key or llm_service.openai_api_key.startswith("sk-placeholder"):
        raise SystemExit("[SKIP] Set OPENAI_API_KEY in backend/.env to run this test.")

    print("=" * 52)
    print(" LIVE OPENAI CHAT TEST ")
    print(f" Model: {llm_service.chat_model}")
    print("=" * 52)

    print("\n--- Opening message (turn 0) ---")
    t0 = time.time()
    opening = llm_service.generate_opening_message(artwork)
    opening_ms = (time.time() - t0) * 1000
    print(f"Response time: {opening_ms:.0f} ms")
    print(json.dumps(opening, indent=2))

    if HEURISTIC_MARKER in opening.get("message", ""):
        raise SystemExit("[FAIL] Opening message matches heuristic fallback.")

    print("\n--- Conversation turn 1 ---")
    t0 = time.time()
    turn1 = llm_service.process_turn(
        history=[{"sender": "assistant", "content": opening["message"]}],
        current_user_message="I love the swirling deep blues and golden stars against the night sky.",
        artwork_metadata_list=artwork,
        turn_count=1,
        previous_context_summary=opening.get("extracted_context"),
    )
    turn1_ms = (time.time() - t0) * 1000
    print(f"Response time: {turn1_ms:.0f} ms")
    print(json.dumps(turn1, indent=2))

    if HEURISTIC_MARKER in turn1.get("message", ""):
        raise SystemExit("[FAIL] Turn 1 matches heuristic fallback.")

    print("\n[OK] Real OpenAI JSON responses confirmed (not heuristic fallback).")
    print(f"Total time: {opening_ms + turn1_ms:.0f} ms")


if __name__ == "__main__":
    main()
