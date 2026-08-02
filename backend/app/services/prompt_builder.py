"""
prompt_builder.py
=================
Builds the image-generation prompt from a session's context_summary and the
reference artworks' metadata (including what the vision model saw in them).
Kept separate so the prompt can be inspected, tuned, or swapped without
touching any API plumbing.
"""

from typing import Dict, Any, List, Optional


STYLE_TRANSLATIONS: Dict[str, str] = {
    "Post-Impressionism": "thick expressive brushstrokes, vivid non-naturalistic colour, emotional intensity",
    "Impressionism": "loose feathery brushwork, natural light effects, soft colour dabs",
    "High Renaissance": "classical harmony, balanced composition, idealised figures, sfumato shading",
    "Dutch Golden Age": "dramatic chiaroscuro lighting, rich deep shadows, photorealistic texture",
    "Ukiyo-e": "flat bold outlines, woodblock print texture, limited vivid palette, stylised waves",
    "Surrealism": "dreamlike juxtaposition, hyper-real precision, impossible physics, uncanny imagery",
    "Expressionism / Symbolism": "distorted forms, raw emotional colour, anguished lines, symbolic imagery",
    "Art Nouveau / Vienna Secession": "ornate gold-leaf patterns, flowing organic lines, mosaic decorations",
    "Spanish Baroque": "complex compositions, deep chiaroscuro, psychological depth, monumental scale",
    "Early Renaissance": "tempera technique, gilded backgrounds, devotional iconography, linear perspective",
    "American Realism": "cinematic artificial light, urban isolation, clean architectural lines",
    "Post-Impressionism / Pointillism": "thousands of small pure-colour dots, optical blending, scientific precision",
    "Surrealism / Mexican Folk Art": "vibrant tropical palette, symbolic animals, introspective self-portrait",
}


def build_image_prompt(
    context_summary: Dict[str, Any],
    artwork_metadata_list: List[Dict[str, Any]],
) -> str:
    """
    Constructs a rich, detailed image generation prompt.

    Parameters
    ----------
    context_summary : dict
        The accumulated context from the conversation:
        - artistic_preferences
        - personal_context
        - desired_mood
        - color_palette_notes
        - composition_notes
        - inspiration_level  ("loose" | "balanced" | "near")
    artwork_metadata_list : list[dict]
        Reference artwork(s) metadata (title, artist, movement_style, description).

    Returns
    -------
    str
        A single string prompt ready to send to DALL-E 3 / Stable Diffusion.
    """
    references = artwork_metadata_list or []
    primary = references[0] if references else {}
    title = primary.get("title", "artwork")
    artist = primary.get("artist", "")
    movement = primary.get("movement_style", "")
    description = primary.get("description", "")

    # Translate movement to visual style language
    style_cue = STYLE_TRANSLATIONS.get(movement, movement)

    inspiration_level = context_summary.get("inspiration_level", "balanced")
    colors = context_summary.get("color_palette_notes", "").strip()
    mood = context_summary.get("desired_mood", "").strip()
    artistic_prefs = context_summary.get("artistic_preferences", "").strip()
    personal_ctx = context_summary.get("personal_context", "").strip()
    composition = context_summary.get("composition_notes", "").strip()

    # --- Inspiration-level framing ---
    # With several references the piece is a blend, so the framing names all of
    # them — selecting multiple artworks is a core part of the feature, not a
    # case where the extras get quietly dropped.
    def _name(art: Dict[str, Any]) -> str:
        art_title = art.get("title", "artwork")
        art_artist = art.get("artist", "")
        if art.get("is_user_upload") or not art_artist:
            return f"'{art_title}'"
        return f"'{art_title}' by {art_artist}"

    if len(references) > 1:
        names = ", ".join(_name(a) for a in references[:4])
        if inspiration_level == "near":
            framing = (
                f"A close reinterpretation blending {names}, faithfully preserving their "
                f"compositional structure and colour palettes in a single new work."
            )
        elif inspiration_level == "loose":
            framing = (
                f"An artwork loosely inspired by the shared emotional atmosphere of {names}, "
                f"capturing their combined spirit rather than their visual form."
            )
        else:
            framing = (
                f"An original artwork that fuses the visual languages of {names} into one "
                f"wholly new composition, balancing what each contributes."
            )
    elif inspiration_level == "near":
        framing = (
            f"A close reinterpretation of {_name(primary)}, "
            f"faithfully preserving the original's composition and colour palette "
            f"while reimagined as a fresh original work."
        )
    elif inspiration_level == "loose":
        framing = (
            f"An artwork loosely inspired by the emotional atmosphere of {_name(primary)}, "
            f"capturing its spirit rather than its visual form."
        )
    else:  # balanced
        framing = (
            f"An original artwork stylistically inspired by {_name(primary)}, "
            f"drawing on its visual language while being a wholly new composition."
        )

    # --- Style section ---
    movements = [m for m in (a.get("movement_style") for a in references) if m]
    unique_movements = list(dict.fromkeys(movements))
    if len(unique_movements) > 1:
        cues = [STYLE_TRANSLATIONS.get(m, m) for m in unique_movements[:3]]
        style_section = (
            f"Rendered as a fusion of {' and '.join(unique_movements[:3])} "
            f"({'; '.join(cues)})"
        )
    elif movement:
        style_section = f"Rendered in the style of {movement}"
        if style_cue and style_cue != movement:
            style_section += f" ({style_cue})"
    else:
        style_section = ""

    # --- Visual grounding from the reference image itself ---
    # A user upload has no movement or description to lean on, so what the
    # vision model saw is the only thing anchoring the new piece to the source.
    visual_cues = []
    for art in references[:2]:
        analysis = art.get("visual_analysis") or {}
        cue = " ".join(
            str(analysis.get(key, "")).strip()
            for key in ("subject", "technique")
            if analysis.get(key)
        ).strip()
        if not cue:
            cue = (art.get("visual_summary") or "").splitlines()[0].strip() if art.get("visual_summary") else ""
        if cue:
            visual_cues.append(cue[:160])
    visual_section = (
        f"Visual qualities drawn from the reference: {' / '.join(visual_cues)}." if visual_cues else ""
    )

    # --- Colour section ---
    colour_section = ""
    if colors:
        colour_section = f"Dominant colour palette: {colors}."

    # --- Mood & composition ---
    mood_section = ""
    if mood:
        mood_section = f"Overall mood and emotional tone: {mood}."

    composition_section = ""
    if composition:
        composition_section = f"Composition notes: {composition}."

    # --- Personal meaning (hints for subject) ---
    personal_section = ""
    if personal_ctx:
        # Trim to first 120 chars so it doesn't dominate
        short_personal = personal_ctx[:120].rstrip()
        personal_section = f"Personal context for the piece: {short_personal}."

    # --- Quality booster ---
    quality = (
        "Museum-quality fine art, highly detailed, masterful technique, "
        "dramatic lighting, visually striking composition, 4K resolution."
    )

    # Assemble prompt
    parts = [
        framing,
        style_section,
        visual_section,
        colour_section,
        mood_section,
        composition_section,
        personal_section,
        quality,
    ]
    prompt = " ".join(p for p in parts if p).strip()

    # Diffusion models degrade on very long prompts; hard-truncate as a safeguard
    return prompt[:1100]


def build_critique_user_message(
    reference_artwork: Dict[str, Any],
    generated_artwork_prompt: str,
    generated_artwork_url: str,
    generated_visual_reading: Optional[str] = None,
    additional_references: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Builds the user message sent to the LLM to generate a structured critique.

    `generated_visual_reading` is the vision model's description of the image
    that was actually produced. When present the critic judges the real artwork
    rather than the prompt that requested it.
    """
    title = reference_artwork.get("title", "Untitled")
    artist = reference_artwork.get("artist", "Unknown")
    movement = reference_artwork.get("movement_style", "")
    description = reference_artwork.get("description", "")
    reference_visual = (reference_artwork.get("visual_summary") or "").strip()

    reference_block = f"""REFERENCE ARTWORK:
- Title: {title}
- Artist: {artist}
- Movement/Style: {movement}
- Description: {description}"""
    if reference_visual:
        reference_block += f"\n- What the image shows:\n{reference_visual}"

    for extra in additional_references or []:
        reference_block += (
            f"\n\nADDITIONAL REFERENCE: '{extra.get('title', 'Untitled')}'"
            f" by {extra.get('artist', 'Unknown')} ({extra.get('movement_style', '')})"
        )
        extra_visual = (extra.get("visual_summary") or "").strip()
        if extra_visual:
            reference_block += f"\n- What the image shows:\n{extra_visual}"

    generated_block = f"""GENERATED ARTWORK:
- Generation Prompt Used: {generated_artwork_prompt}
- Image URL: {generated_artwork_url}"""
    if generated_visual_reading:
        generated_block += (
            f"\n- What the generated image ACTUALLY shows (observed directly):\n"
            f"{generated_visual_reading}\n"
            f"Base your critique of the generated piece on this observation, not on the prompt."
        )
    else:
        generated_block += (
            "\n- No visual reading was available, so infer cautiously from the prompt "
            "and avoid claiming specific details you cannot verify."
        )

    return f"""Please provide a structured critique of the following two artworks.

{reference_block}

{generated_block}

Write a MEDIUM-LENGTH critique: 2-3 sentences for each of composition, color_theory,
symbolism and emotional_impact; 2-3 short bullet items for strengths and weaknesses;
and 3-4 sentences for the comparison. Be specific about these two works — do not
write generic art-criticism that could apply to any painting.

Use the following JSON structure:

{{
  "reference_critique": {{
    "composition": "...",
    "color_theory": "...",
    "symbolism": "...",
    "emotional_impact": "...",
    "strengths": ["...", "..."],
    "weaknesses": ["...", "..."]
  }},
  "generated_critique": {{
    "composition": "...",
    "color_theory": "...",
    "symbolism": "...",
    "emotional_impact": "...",
    "strengths": ["...", "..."],
    "weaknesses": ["...", "..."]
  }},
  "comparison": "A paragraph comparing both works, how the generated piece interprets the reference, what it captures and what differs..."
}}

Output ONLY the raw JSON object, no markdown fences."""
