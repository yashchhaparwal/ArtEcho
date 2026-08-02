import json
from unittest.mock import MagicMock
from app.core.config import settings
from app.services.llm_provider import LLMProvider


def test_conversation_uses_ollama_api(monkeypatch):
    def mock_post_impl(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {
                "content": json.dumps({
                    "message": "Ollama response",
                    "ready_to_generate": False,
                    "extracted_context": {
                        "artistic_preferences": "vibrant blue",
                        "personal_context": "living room",
                        "desired_mood": "calm",
                        "color_palette_notes": "blue",
                        "composition_notes": "centered",
                        "inspiration_level": "balanced",
                    },
                })
            }
        }
        return mock_resp

    mock_post = MagicMock(side_effect=mock_post_impl)

    mock_client = MagicMock()
    mock_client.__enter__.return_value.post = mock_post

    monkeypatch.setattr("app.services.llm_provider.httpx.Client", lambda timeout=300.0: mock_client)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "qwen2.5:7b")

    provider = LLMProvider()

    result = provider.process_turn(
        history=[],
        current_user_message="I love blue colors for my living room",
        artwork_metadata_list=[{"title": "Sunset", "artist": "Test"}],
        turn_count=1,
    )

    assert result["message"] == "Ollama response"
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "http://localhost:11434/api/chat"
    assert call_args[1]["json"]["model"] == "qwen2.5:7b"
    assert call_args[1]["json"]["stream"] is False
    assert call_args[1]["json"]["format"] == "json"
