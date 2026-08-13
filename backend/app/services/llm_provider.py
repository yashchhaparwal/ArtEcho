import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.profiling import set_llm_metrics

logger = logging.getLogger(__name__)

MUSE_SYSTEM_PROMPT = """
You are Muse, an expert art curator and empathetic creative assistant.
Your goal is to guide the user in a natural, insightful dialogue about one or more reference artworks they have chosen.
Through this conversation, you co-create ideas for a brand new AI-generated piece of artwork inspired by their reference.

### YOUR OBJECTIVE & RULES:
1. ASK EXACTLY ONE QUESTION AT A TIME. Keep your responses concise, warm, and engaging (2-4 sentences max per response).
2. Ground every question in what is ACTUALLY VISIBLE in the reference artwork. Each artwork below may include a
   VISUAL READING describing what the image really depicts — its subject, colours, composition, technique and mood.
   Use those concrete details to ask specific, pointed questions ("the way the cypress cuts up through the swirling
   sky — is that turbulence what pulls you in, or the calm of the village beneath it?"). Never ask generic questions
   like "what do you like about it?" when you can name something real in the picture.
3. Balance artistic/visual exploration (color scheme, composition, subject, lighting, mood) with personal context (memories, emotions, intended room/space to display the piece, desired feeling).
4. Evaluate the conversation signal after each turn:
   - ARTISTIC SIGNAL: Does the user describe specific visual preferences (colors, composition, style, lighting)?
   - PERSONAL SIGNAL: Does the user describe personal meaning, memories, space placement, or emotional desired vibe?
5. Set `ready_to_generate` to `true` once BOTH a clear artistic signal AND a clear personal signal have been captured,
   or immediately if the user asks to generate. `ready_to_generate` UNLOCKS the generate button — it does NOT end
   the conversation.
6. THE USER DECIDES HOW LONG THE CONVERSATION LASTS. Never announce that the conversation is over and never refuse to
   continue. Once ready, tell them they can generate whenever they like AND offer one more avenue worth exploring, so
   a user who wants a longer session can keep going and a user who wants a short one can stop immediately.
7. ALWAYS output ONLY a raw JSON object matching the exact schema below.
8. In `extracted_context`, include ONLY the fields whose value CHANGED this turn
   (i.e. the user just told you something new about them). OMIT every field that
   is unchanged — the server already has those values from PREVIOUS CONTEXT
   SUMMARY and will keep them. For a field you do include, give its complete
   updated value, not just the new fragment. If nothing changed this turn,
   `extracted_context` must be an empty object {}.

### REQUIRED JSON SCHEMA:
{
  "message": "Your conversational response and next single question to the user",
  "ready_to_generate": boolean (true once both signals are captured or the user asks to generate),
  "extracted_context": {
    // Include ONLY changed fields. Valid keys:
    "artistic_preferences": "Summary of visual preferences (colors, composition, style, lighting)",
    "personal_context": "Summary of personal memories, intended space, or emotional connection",
    "desired_mood": "Core emotional tone/vibe desired for the new piece",
    "color_palette_notes": "Colors or tonal qualities highlighted",
    "composition_notes": "Subject matter, arrangement, or structural notes",
    "inspiration_level": "loose" | "balanced" | "near" (inferred: 'loose' for thematic/vibe, 'balanced' for stylized interpretation, 'near' for close reinterpretation)
  }
}
"""

# --- Generation tuning -------------------------------------------------------
# Measured on this host (qwen2.5:7b, Q4_K_M, CPU-only): generation runs at
# ~1.5 tok/s while prompt eval runs at ~24 tok/s. An output token therefore
# costs ~16x an input token, so the ceiling below is a tail-latency guard: a
# runaway turn that ignored the "2-4 sentences" rule would otherwise cost
# minutes. Typical turns emit ~142 tokens and are unaffected.
MAX_OUTPUT_TOKENS = 350

# The critique is a single JSON blob holding two full critiques plus a
# comparison — far larger than a conversational turn. Capping it at
# MAX_OUTPUT_TOKENS truncates the JSON mid-string, json.loads throws, and the
# caller silently serves the canned fallback text instead of a real critique.
MAX_CRITIQUE_TOKENS = 1400

# HTTP read timeouts. Generation on a CPU-only host runs at roughly 1.5 tok/s,
# so a full critique can legitimately take many minutes — a conversational
# turn's budget is nowhere near enough, and a timeout here is indistinguishable
# from a real failure to the caller, which then serves boilerplate.
DEFAULT_HTTP_TIMEOUT = 300.0
CRITIQUE_HTTP_TIMEOUT = 1200.0

# The streamed prose reply is bound by the "2-4 sentences" rule (~35 tokens
# measured), so this ceiling only guards against a runaway turn.
MAX_PROSE_TOKENS = 160

# Keep the model resident between turns. Ollama's default is 5 minutes; on this
# host a cold load of the 4.71GB weights costs ~110s under memory pressure.
OLLAMA_KEEP_ALIVE = "30m"

# Conversation history is unbounded in the DB. Measured growth is modest
# (~110 tokens at 4 messages, ~1132 projected at 16), but the cap keeps prompt
# eval from drifting upward over a long session. Only the oldest turns drop;
# the running context_summary already carries their substance forward.
MAX_HISTORY_MESSAGES = 10

# The only keys allowed into context_summary, so a malformed delta cannot
# introduce junk fields.
CONTEXT_FIELDS = (
    "artistic_preferences",
    "personal_context",
    "desired_mood",
    "color_palette_notes",
    "composition_notes",
    "inspiration_level",
)

# --- Two-call split (streaming path) -----------------------------------------
# The single-call design forces one JSON blob containing both the prose reply
# and the context object, so nothing can be shown until the whole thing is
# generated (~180s measured). Splitting lets call 1 stream prose immediately.
#
# Call 1 drops the JSON schema entirely — the model writes 2-4 sentences and
# nothing else, so output falls from ~142 tokens to ~35.
MUSE_PROSE_SYSTEM_PROMPT = """
You are Muse, an expert art curator and empathetic creative assistant.
Your goal is to guide the user in a natural, insightful dialogue about one or more reference artworks they have chosen.
Through this conversation, you co-create ideas for a brand new AI-generated piece of artwork inspired by their reference.

### YOUR OBJECTIVE & RULES:
1. ASK EXACTLY ONE QUESTION AT A TIME. Keep your responses concise, warm, and engaging (2-4 sentences max per response).
2. Ground your questions in what is ACTUALLY VISIBLE in the reference artwork. Each artwork below may include a
   VISUAL READING of what the image really depicts — name real details from it rather than asking generic questions.
3. Balance artistic/visual exploration (color scheme, composition, subject, lighting, mood) with personal context (memories, emotions, intended room/space to display the piece, desired feeling).
4. If the conversation has already captured both a clear artistic preference AND a clear personal/emotional signal,
   tell them they can generate whenever they're ready — then offer one more thread worth exploring. THE USER DECIDES
   WHEN TO STOP: never declare the conversation finished and never refuse to keep talking.
5. Reply with PLAIN PROSE ONLY. No JSON, no markdown fences, no preamble, no labels.
"""

# Call 2 runs on a deliberately small prompt: it does NOT resend the persona
# rules, artwork metadata or full history — only the exchange that just
# happened plus the previous summary. Measured prompt eval is ~26 tok/s, so
# keeping this call short is what makes the split a net win.
CONTEXT_EXTRACTION_PROMPT = """
Extract structured preferences from an art conversation exchange.
Respond with ONLY a raw JSON object, no markdown fences.

Include ONLY fields whose value CHANGED in this exchange. Omit unchanged fields
entirely — the caller keeps their previous values. If nothing changed, return {}.
For a field you include, give its complete updated value.

CRITICAL: every value must be drawn from what the USER actually said, in their own
terms. Never copy the field descriptions below into a value — they describe what
each field is for, they are not example answers. If the user said nothing relevant
to a field, omit that field.

Fields (description → what to put in the value):
  artistic_preferences - what the user said about how the piece should look
  personal_context     - what the user said about memories, meaning, or where it will hang
  desired_mood         - the emotional tone the user asked for
  color_palette_notes  - specific colours or tones the user named
  composition_notes    - subject matter or arrangement the user described
  inspiration_level    - exactly one of: "loose", "balanced", "near"
  ready_to_generate    - true only if BOTH a clear artistic preference AND a clear personal signal are now captured

Good:  {"color_palette_notes": "deep blues and gold", "personal_context": "reminds them of summers at their grandmother's house"}
Bad:   {"color_palette_notes": "colors or tonal qualities highlighted"}
"""

# Values the model sometimes parrots back from the schema instead of extracting a
# real answer. Letting these through pollutes the image prompt with meaningless
# filler like "visual preferences (colors, composition, style, lighting)".
PLACEHOLDER_VALUES = frozenset(
    {
        "visual preferences (colors, composition, style, lighting)",
        "personal memories, intended space, emotional connection",
        "core emotional tone/vibe desired",
        "colors or tonal qualities highlighted",
        "subject matter, arrangement, structural notes",
        "summary of visual preferences (colors, composition, style, lighting)",
        "summary of personal memories, intended space, or emotional connection",
        "what the user said about how the piece should look",
        "what the user said about memories, meaning, or where it will hang",
        "the emotional tone the user asked for",
        "specific colours or tones the user named",
        "subject matter or arrangement the user described",
        "string",
        "n/a",
        "none",
        "unknown",
        "not specified",
    }
)

CRITIQUE_SYSTEM_PROMPT = """
You are an expert art critic with deep knowledge of art history, aesthetics, colour theory, and composition.
Provide balanced, insightful, and constructive critiques. Be specific with your observations.
Always respond with ONLY a valid JSON object matching the schema provided — no markdown fences, no extra text.
"""


class LLMProvider:
    def __init__(self):
        self.ollama_base_url = (
            getattr(settings, "OLLAMA_BASE_URL", None)
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434"
        ).strip()
        self.ollama_model = (
            getattr(settings, "OLLAMA_MODEL", None)
            or os.getenv("OLLAMA_MODEL")
            or "qwen2.5:7b"
        ).strip()

    def generate_opening_message(self, artwork_metadata_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate initial assistant welcome message and opening question when a session starts.
        """
        artworks = artwork_metadata_list or []
        titles = ", ".join(
            f"'{a.get('title') or 'their uploaded image'}'"
            + (f" by {a['artist']}" if a.get("artist") and not a.get("is_user_upload") else "")
            for a in artworks
        )
        multi_note = (
            "\nThey chose several references together, so acknowledge what the pieces share "
            "or how they contrast, and ask which quality they want carried into the new work."
            if len(artworks) > 1
            else ""
        )
        prompt = (
            f"The user has just selected the following reference artwork(s): {titles}.{multi_note}\n"
            f"Write a welcoming opening message that names one CONCRETE visual detail you can see in the work "
            f"(use the VISUAL READING above — a colour, a shape, a gesture, a contrast), then ask your first "
            f"question about what specifically draws them to it. Be pointed, not generic."
        )

        return self.call_llm(history=[], current_user_message=prompt, artwork_metadata_list=artwork_metadata_list, turn_count=0)

    def process_turn(
        self,
        history: List[Dict[str, str]],
        current_user_message: str,
        artwork_metadata_list: List[Dict[str, Any]],
        turn_count: int,
        previous_context_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process a user turn in the chat session, updating context summary and assessing readiness.

        The model is asked to return only the context fields that changed this
        turn (see rule 6 in MUSE_SYSTEM_PROMPT) — re-emitting all six fields
        verbatim was measured at ~90 of ~142 generated tokens, and generation is
        by far the most expensive stage. The delta is merged back here, so
        callers still receive the complete accumulated summary exactly as before.
        """
        result = self.call_llm(
            history=history,
            current_user_message=current_user_message,
            artwork_metadata_list=artwork_metadata_list,
            turn_count=turn_count,
            previous_context_summary=previous_context_summary,
        )
        result["extracted_context"] = self._merge_context(
            previous_context_summary, result.get("extracted_context")
        )
        return result

    @staticmethod
    def has_enough_context(context_summary: Optional[Dict[str, Any]]) -> bool:
        """
        True once both signals the brief calls for are captured: something about
        how the piece should LOOK, and something PERSONAL about why.

        Derived from the accumulated summary rather than trusting the model to
        remember to set a `ready_to_generate` flag — a small local model often
        omits it, which used to leave the generate button locked even after the
        user had said plenty.
        """
        summary = context_summary or {}

        def filled(*keys: str) -> bool:
            return any(str(summary.get(key) or "").strip() for key in keys)

        artistic = filled("artistic_preferences", "color_palette_notes", "composition_notes")
        personal = filled("personal_context", "desired_mood")
        return artistic and personal

    @staticmethod
    def _merge_context(
        previous: Optional[Dict[str, Any]], delta: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Fold a partial context update onto the previous summary.

        An omitted key means "unchanged", so the previous value is kept. Blank
        values are ignored too — the model must never be able to erase context
        it simply chose not to restate.
        """
        merged = dict(previous or {})
        for key in CONTEXT_FIELDS:
            value = (delta or {}).get(key)
            if isinstance(value, str):
                value = value.strip()
                # The model occasionally echoes the schema's own field
                # description instead of extracting an answer. Storing that
                # would put meaningless filler into the image prompt.
                if value.lower().rstrip(".") in PLACEHOLDER_VALUES:
                    logger.info(f"Discarded placeholder echo for '{key}': {value!r}")
                    continue
            if value:
                merged[key] = value
        return merged

    def stream_prose_turn(
        self,
        history: List[Dict[str, str]],
        current_user_message: str,
        artwork_metadata_list: List[Dict[str, Any]],
        previous_context_summary: Optional[Dict[str, Any]] = None,
        include_artwork_description: bool = True,
    ):
        """
        Call 1 of the split: stream the conversational reply token by token.

        Yields text fragments as they arrive. Raises on transport failure so the
        caller can fall back to the non-streaming path.
        """
        artworks_block = self._format_artworks(
            artwork_metadata_list, include_description=include_artwork_description
        )
        # The system block holds only what is fixed for the whole session, so
        # llama.cpp's prefix cache can reuse it across turns. The accumulated
        # context summary used to live here too — and because it changes every
        # turn, it invalidated the cache and forced all ~600 prompt tokens to be
        # re-evaluated each time (measured at ~15s per turn on a 2-core CPU).
        # Moving it onto the final user message keeps the model equally informed
        # while leaving everything before that message byte-identical.
        system_prompt = (
            f"{MUSE_PROSE_SYSTEM_PROMPT}\n\n"
            f"REFERENCE ARTWORKS:\n{artworks_block}"
        )
        messages = [{"role": "system", "content": system_prompt}]
        for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
            role = "user" if item.get("sender") == "user" else "assistant"
            messages.append({"role": role, "content": item.get("content", "")})

        prev_summary = previous_context_summary or {}
        if any(prev_summary.values()):
            final_message = (
                f"WHAT YOU ALREADY KNOW ABOUT THE USER:\n{json.dumps(prev_summary)}\n\n"
                f"{current_user_message or ''}"
            )
        else:
            final_message = current_user_message or ""
        messages.append({"role": "user", "content": final_message})

        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.7, "num_predict": MAX_PROSE_TOKENS},
        }
        endpoint = f"{self.ollama_base_url.rstrip('/')}/api/chat"

        t0 = time.perf_counter()
        first_token_at = None
        with httpx.Client(timeout=300.0) as client:
            with client.stream("POST", endpoint, json=payload) as res:
                res.raise_for_status()
                for line in res.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    fragment = chunk.get("message", {}).get("content", "")
                    if fragment:
                        if first_token_at is None:
                            first_token_at = time.perf_counter() - t0
                        yield fragment
                    if chunk.get("done"):
                        ns = 1e9
                        set_llm_metrics({
                            "stage": "prose (streamed)",
                            "time_to_first_token": round(first_token_at or 0.0, 2),
                            "prompt_tokens": chunk.get("prompt_eval_count", 0),
                            "generation_tokens": chunk.get("eval_count", 0),
                            "prompt_eval_secs": chunk.get("prompt_eval_duration", 0) / ns,
                            "generation_secs": chunk.get("eval_duration", 0) / ns,
                            "load_secs": chunk.get("load_duration", 0) / ns,
                        })

    def extract_context(
        self,
        current_user_message: str,
        assistant_reply: str,
        previous_context_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call 2 of the split: derive the context delta from the exchange that just
        happened. Deliberately given a minimal prompt (no persona, no artwork
        metadata, no history) because prompt eval is charged per token.
        """
        return self.extract_context_from_exchanges(
            [(current_user_message, assistant_reply)], previous_context_summary
        )

    def extract_context_from_exchanges(
        self,
        exchanges: List[tuple[str, str]],
        previous_context_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Derive the context delta from one or more exchanges at once.

        Batching matters on a CPU-only host: this call costs roughly as much as
        the reply itself, and almost all of that is fixed overhead — the
        extraction system prompt is ~360 tokens while an exchange adds ~60 and
        the answer is under 30. Folding two turns into a single call therefore
        costs barely more than one and halves how often the model has to swap
        between the conversation prompt and this one, which is what made the
        alternating calls thrash the prefix cache.
        """
        if not exchanges:
            return {}

        summary_block = f"PREVIOUS SUMMARY:\n{json.dumps(previous_context_summary or {})}"

        if len(exchanges) == 1:
            # The single-turn wording the extraction prompt was tuned against.
            user_said, assistant_replied = exchanges[0]
            user_message = (
                f"{summary_block}\n\n"
                f"USER SAID:\n{user_said}\n\n"
                f"ASSISTANT REPLIED:\n{assistant_replied}"
            )
        else:
            # A plain transcript. Numbering the turns instead ("USER SAID 1/2")
            # was measured at 35s for a single field, against 5-9s and grounded
            # values this way; and instructing the model to "cover every user
            # line" made it invent colours nobody mentioned, which would end up
            # in the image prompt.
            lines = "\n".join(
                f"USER: {user_said}\nASSISTANT: {assistant_replied}"
                for user_said, assistant_replied in exchanges
            )
            user_message = f"{summary_block}\n\nEXCHANGE:\n{lines}"

        raw = self._call_ollama(
            system_prompt=CONTEXT_EXTRACTION_PROMPT,
            user_message=user_message,
            temperature=0.3,
        )
        return raw if isinstance(raw, dict) else {}

    def generate_critique(self, user_message: str, primary_artwork_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a structured critique response via the configured LLM provider.

        Falling back here means the user reads generic boilerplate that mentions
        no real detail of their piece, so the failure is logged loudly rather
        than at warning level, and a partial-but-real critique is preferred over
        the canned text whenever one can be salvaged.
        """
        try:
            result = self._call_ollama(
                system_prompt=CRITIQUE_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.6,
                max_tokens=MAX_CRITIQUE_TOKENS,
                timeout=CRITIQUE_HTTP_TIMEOUT,
            )
            if self._critique_is_usable(result):
                return result
            logger.error(
                "Critique response was missing required sections; "
                f"got keys {list(result)}. Serving fallback text."
            )
        except Exception as exc:
            logger.error(f"Ollama critique call failed, serving fallback text: {exc}")
        return self._heuristic_critique(primary_artwork_meta or {})

    @staticmethod
    def _critique_is_usable(result: Any) -> bool:
        """A critique must actually contain prose for both artworks."""
        if not isinstance(result, dict):
            return False
        for key in ("reference_critique", "generated_critique"):
            section = result.get(key)
            if not isinstance(section, dict):
                return False
            if not any(isinstance(v, str) and v.strip() for v in section.values()):
                return False
        return True

    def call_llm(
        self,
        history: List[Dict[str, str]],
        current_user_message: str,
        artwork_metadata_list: List[Dict[str, Any]],
        turn_count: int,
        previous_context_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            return self._call_ollama(
                history=history,
                current_user_message=current_user_message,
                artwork_metadata_list=artwork_metadata_list,
                turn_count=turn_count,
                previous_context_summary=previous_context_summary,
                system_prompt=MUSE_SYSTEM_PROMPT,
                temperature=0.7,
            )
        except Exception as exc:
            logger.warning(f"Ollama call failed, falling back to heuristic provider: {exc}")

        return self._call_heuristic_fallback(history, current_user_message, artwork_metadata_list, turn_count, previous_context_summary)

    def _call_ollama(
        self,
        history: Optional[List[Dict[str, str]]] = None,
        current_user_message: Optional[str] = None,
        artwork_metadata_list: Optional[List[Dict[str, Any]]] = None,
        turn_count: int = 0,
        previous_context_summary: Optional[Dict[str, Any]] = None,
        system_prompt: str = MUSE_SYSTEM_PROMPT,
        temperature: float = 0.7,
        user_message: Optional[str] = None,
        max_tokens: int = MAX_OUTPUT_TOKENS,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> Dict[str, Any]:
        if user_message is not None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
        else:
            prev_summary_str = json.dumps(previous_context_summary or {}, indent=2)
            payload_system_prompt = (
                f"{system_prompt}\n\n"
                f"REFERENCE ARTWORKS:\n{self._format_artworks(artwork_metadata_list)}\n\n"
                f"TURNS SO FAR: {turn_count} (there is no limit — the user decides when to stop)\n"
                f"PREVIOUS CONTEXT SUMMARY:\n{prev_summary_str}\n"
            )
            messages = [{"role": "system", "content": payload_system_prompt}]
            for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
                role = "user" if item.get("sender") == "user" else "assistant"
                messages.append({"role": role, "content": item.get("content", "")})
            messages.append({"role": "user", "content": current_user_message or ""})

        endpoint = f"{self.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        prompt_chars = sum(len(m["content"]) for m in messages)
        t_http = time.perf_counter()
        with httpx.Client(timeout=timeout) as client:
            res = client.post(endpoint, json=payload)
            res.raise_for_status()
            data = res.json()
            raw_text = data.get("message", {}).get("content", "").strip()
        http_secs = time.perf_counter() - t_http

        # Hitting the token ceiling truncates the JSON mid-string, so the parse
        # below fails with a confusing decode error. Name the real cause.
        if data.get("done_reason") == "length":
            logger.warning(
                f"Model output hit the {max_tokens}-token ceiling and was truncated; "
                f"the response is likely unparseable JSON."
            )

        # Ollama reports its own breakdown in nanoseconds.
        t_parse = time.perf_counter()
        parsed = self._parse_json_response(raw_text)
        parse_secs = time.perf_counter() - t_parse

        ns = 1e9
        prompt_tokens = data.get("prompt_eval_count", 0)
        gen_tokens = data.get("eval_count", 0)
        prompt_secs = data.get("prompt_eval_duration", 0) / ns
        gen_secs = data.get("eval_duration", 0) / ns
        set_llm_metrics({
            "http_secs": http_secs,
            "parse_secs": parse_secs,
            "load_secs": data.get("load_duration", 0) / ns,
            "prompt_eval_secs": prompt_secs,
            "generation_secs": gen_secs,
            "prompt_tokens": prompt_tokens,
            "generation_tokens": gen_tokens,
            "prompt_chars": prompt_chars,
            "message_count": len(messages),
            "history_turns": max(len(messages) - 2, 0),
            "prompt_tok_per_s": round(prompt_tokens / prompt_secs, 1) if prompt_secs else None,
            "gen_tok_per_s": round(gen_tokens / gen_secs, 1) if gen_secs else None,
            "done_reason": data.get("done_reason"),
        })
        return parsed

    @staticmethod
    def _format_artworks(
        artwork_metadata_list: Optional[List[Dict[str, Any]]],
        include_description: bool = True,
    ) -> str:
        """
        Render the reference artworks as readable text rather than raw JSON.

        `visual_summary` — what the vision model actually saw in the image — is
        given its own labelled block because it is the only source of concrete
        detail for a user upload, which has no meaningful title or artist.

        `include_description` exists because prompt evaluation dominates latency
        on CPU-only hosts (measured at ~21 tokens/sec on a 2-core i3, so every
        70 tokens of catalogue prose costs the user another ~3 seconds before a
        single word appears). The opening turn is asked to name a concrete
        VISUAL detail, which comes from the visual reading rather than the
        encyclopedic blurb — so that turn drops the description and keeps
        everything that actually shapes the question.
        """
        if not artwork_metadata_list:
            return "(none)"

        fields = [
            ("title", "Title"),
            ("artist", "Artist"),
            ("year", "Year"),
            ("movement_style", "Movement/Style"),
            ("medium", "Medium"),
        ]
        if include_description:
            fields.append(("description", "Description"))

        blocks = []
        for index, art in enumerate(artwork_metadata_list, start=1):
            lines = [f"--- Artwork {index} ---"]
            if art.get("is_user_upload"):
                lines.append("Source: uploaded by the user (no catalogue metadata — rely on the visual reading)")
            for key, label in fields:
                value = art.get(key)
                if value:
                    lines.append(f"{label}: {value}")
            visual = (art.get("visual_summary") or "").strip()
            if visual:
                lines.append(f"VISUAL READING (what the image actually shows):\n{visual}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    @staticmethod
    def _parse_json_response(raw_text: str) -> Dict[str, Any]:
        # Clean markdown code block formatting if present
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        return json.loads(raw_text)

    def _call_heuristic_fallback(
        self,
        history: List[Dict[str, str]],
        current_user_message: str,
        artwork_metadata_list: List[Dict[str, Any]],
        turn_count: int,
        previous_context_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Intelligent context-aware fallback engine for local/test execution without live API keys.
        Extracts artistic & personal signals from user text and progresses turn-by-turn.
        """
        context = dict(previous_context_summary or {
            "artistic_preferences": "",
            "personal_context": "",
            "desired_mood": "",
            "color_palette_notes": "",
            "composition_notes": "",
            "inspiration_level": "balanced",
        })

        text = current_user_message.lower()
        title = artwork_metadata_list[0].get("title", "artwork") if artwork_metadata_list else "the piece"
        artist = artwork_metadata_list[0].get("artist", "") if artwork_metadata_list else ""

        if turn_count == 0 or not history:
            return {
                "message": (
                    f"Welcome to Muse! I'm thrilled you chose '{title}'{f' by {artist}' if artist else ''}. "
                    f"Its visual atmosphere is so compelling. To start, what specific visual element or color first caught your eye when looking at this work?"
                ),
                "ready_to_generate": False,
                "extracted_context": context,
            }

        artistic_keywords = [
            "blue", "yellow", "gold", "red", "green", "dark", "bright", "vibrant",
            "swirl", "swirling", "brushwork", "light", "shadow", "pastel", "earthy",
            "sky", "star", "stars", "wave", "texture", "color", "composition", "style"
        ]
        found_artistic = [w for w in artistic_keywords if w in text]

        if found_artistic:
            existing_colors = context.get("color_palette_notes", "")
            new_colors = ", ".join(found_artistic)
            context["color_palette_notes"] = f"{existing_colors}, {new_colors}".strip(", ")

            existing_artistic = context.get("artistic_preferences", "")
            context["artistic_preferences"] = f"{existing_artistic} {current_user_message}".strip()

        personal_keywords = [
            "bedroom", "room", "living room", "office", "study", "wall", "home",
            "gallery", "space", "peaceful", "calm", "nostalgic", "energetic",
            "dreamy", "mysterious", "cozy", "hopeful", "dramatic", "memory",
            "reminds", "childhood", "feeling", "feel", "display", "place", "sleep"
        ]
        found_personal = [w for w in personal_keywords if w in text]

        if found_personal:
            existing_mood = context.get("desired_mood", "")
            new_mood = ", ".join(found_personal)
            context["desired_mood"] = f"{existing_mood}, {new_mood}".strip(", ")

            existing_personal = context.get("personal_context", "")
            context["personal_context"] = f"{existing_personal} {current_user_message}".strip()

        direct_generate_request_keywords = [
            "generate", "make a picture", "make the picture", "picture",
            "give me picture", "give me updated picture", "updated picture", "image", "show me"
        ]
        direct_generate_request = any(kw in text for kw in direct_generate_request_keywords)

        if "exact" in text or "replica" in text or "same" in text or "reinterpretation" in text:
            context["inspiration_level"] = "near"
        elif "vibe" in text or "feeling" in text or "loose" in text or "theme" in text:
            context["inspiration_level"] = "loose"
        else:
            context["inspiration_level"] = "balanced"

        has_artistic = bool(context.get("artistic_preferences"))
        has_personal = bool(context.get("personal_context"))
        ready = (has_artistic and has_personal) or (turn_count >= 8) or (
            has_artistic and direct_generate_request
        )

        if ready:
            response_msg = (
                "I have enough direction now. If you're ready, I can create a new artwork "
                "inspired by your preferences and the reference piece. Would you like me "
                "to proceed with image generation?"
            )
        else:
            response_msg = (
                "That's lovely. Tell me a bit more about how you'd like this piece "
                "to feel in your space, or what mood and color palette you want it to convey."
            )

        return {
            "message": response_msg,
            "ready_to_generate": ready,
            "extracted_context": context,
        }

    def _heuristic_critique(self, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta = meta or {}
        title = meta.get("title", "the reference artwork")
        artist = meta.get("artist", "the artist")
        movement = meta.get("movement_style", "the movement")

        return {
            "reference_critique": {
                "composition": (
                    f"'{title}' by {artist} demonstrates masterful compositional control. "
                    f"The arrangement of elements creates a dynamic yet balanced visual flow "
                    f"that guides the viewer's eye through the canvas with deliberate intention."
                ),
                "color_theory": (
                    f"The colour palette of '{title}' is deeply characteristic of the {movement} movement. "
                    f"The chromatic relationships between warm and cool tones create visual tension and harmony, "
                    f"amplifying the emotional resonance of the work."
                ),
                "symbolism": (
                    f"The symbolic vocabulary embedded in '{title}' reflects the cultural and artistic context "
                    f"of the {movement} era, encoding layers of meaning that reward sustained viewing "
                    f"and scholarly analysis."
                ),
                "emotional_impact": (
                    f"The work elicits a profound emotional response through its masterful manipulation "
                    f"of formal elements. The viewer is drawn into an experiential dialogue with the artist's "
                    f"intentions, creating a lasting psychological impression."
                ),
                "strengths": [
                    "Exceptional command of compositional rhythm",
                    "Masterful use of colour to convey emotion",
                    "Rich symbolic and historical layering",
                    "Enduring visual impact and cultural relevance",
                ],
                "weaknesses": [
                    "Reproductions rarely capture the full textural richness of the original medium",
                    "The cultural distance of the period may challenge contemporary interpretive frameworks",
                ],
            },
            "generated_critique": {
                "composition": (
                    "The AI-generated artwork shows a thoughtful interpretation of the compositional "
                    "principles extracted from the conversation context. The spatial arrangement reflects "
                    "the user's stated preferences for visual balance and emotional resonance."
                ),
                "color_theory": (
                    "The colour palette directly reflects the chromatic preferences articulated during the "
                    "guided conversation. The tonal relationships establish the desired mood effectively, "
                    "creating a cohesive visual atmosphere aligned with the user's vision."
                ),
                "symbolism": (
                    "The generated piece translates personal and artistic context into visual symbols, "
                    "embedding the user's described emotional associations into compositional choices "
                    "that personalise the work beyond its reference inspiration."
                ),
                "emotional_impact": (
                    "The generated artwork successfully channels the intended emotional atmosphere described "
                    "by the user — creating an image that resonates with the personal context and "
                    "spatial intentions articulated in the conversation."
                ),
                "strengths": [
                    "Strong alignment with user's stated colour and mood preferences",
                    "Successfully personalises the reference artwork's visual language",
                    "Creates an emotionally coherent atmosphere",
                ],
                "weaknesses": [
                    "AI generation may lack the spontaneous gestural quality of hand-made art",
                    "The prompt-driven approach constrains certain forms of visual surprise and serendipity",
                ],
            },
            "comparison": (
                f"Where '{title}' by {artist} represents a singular artistic vision forged through years of "
                f"mastery within the {movement} tradition, the generated artwork offers a personalised "
                f"reinterpretation — a dialogue between the reference's established visual language and the "
                f"user's own aesthetic sensibilities and emotional needs. The original carries the weight of "
                f"art-historical significance; the generated piece carries personal meaning. Together, they "
                f"demonstrate how contemporary AI tools can translate appreciation into creation."
            ),
        }


llm_service = LLMProvider()
