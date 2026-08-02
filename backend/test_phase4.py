import sys, os, json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_phase4():
    print("=== PHASE 4: IMAGE GENERATION + CRITIQUE TEST ===\n")

    # ── Auth ──────────────────────────────────────────────────────────────────
    login = client.post('/api/v1/auth/login/json', json={'email': 'uploader@example.com', 'password': 'password123'})
    token = login.json()['access_token']
    H = {'Authorization': f'Bearer {token}'}

    # ── Get an artwork ────────────────────────────────────────────────────────
    artworks = client.get('/api/v1/artworks').json()['artworks']
    starry = next(a for a in artworks if 'Starry Night' in a['title'] and 'Rhone' not in a['title'])
    art_id = starry['id']
    print(f"Reference: '{starry['title']}' by {starry['artist']}")

    # ── Create session ────────────────────────────────────────────────────────
    sess_res = client.post('/api/v1/sessions', headers=H, json={'reference_artwork_ids': [art_id]})
    assert sess_res.status_code == 201
    session_id = sess_res.json()['id']
    print(f"Session: {session_id}")

    # ── Send messages to reach ready_to_generate ──────────────────────────────
    msgs = [
        "I'm captivated by the swirling deep blue and the glowing yellow-gold of the stars against the dark sky.",
        "I want to hang it in my living room to evoke a sense of calm wonder before bed."
    ]
    for i, m in enumerate(msgs, 1):
        r = client.post(f'/api/v1/sessions/{session_id}/messages', headers=H, json={'content': m})
        assert r.status_code == 200, f"Message {i} failed: {r.text}"

    sess = client.get(f'/api/v1/sessions/{session_id}', headers=H).json()
    assert sess['is_ready_to_generate'], "Session should be ready!"
    print(f"\nContext Summary:\n{json.dumps(sess['context_summary'], indent=2)}")

    # ── Test prompt builder directly ───────────────────────────────────────────
    from app.services.prompt_builder import build_image_prompt
    prompt = build_image_prompt(sess['context_summary'], [{
        'title': starry['title'], 'artist': starry['artist'],
        'movement_style': starry.get('movement_style', ''), 'description': starry.get('description', '')
    }])
    print(f"\n--- BUILT IMAGE PROMPT ({len(prompt)} chars) ---")
    print(prompt)

    # ── Generate artwork (Generation #1) ──────────────────────────────────────
    gen_res = client.post(f'/api/v1/sessions/{session_id}/generate', headers=H)
    assert gen_res.status_code == 201, f"Generate failed: {gen_res.text}"
    gen_data = gen_res.json()
    gen_id_1 = gen_data['id']
    print(f"\n--- GENERATED ARTWORK #1 ---")
    print(f"  ID:             {gen_id_1}")
    print(f"  generation_index: {gen_data['generation_index']}")
    print(f"  image_url:      {gen_data['image_url']}")
    print(f"  model_provider: {gen_data['model_provider']}")

    # ── Generate critique ─────────────────────────────────────────────────────
    crit_res = client.post(f'/api/v1/sessions/{session_id}/critique', headers=H)
    assert crit_res.status_code == 201, f"Critique failed: {crit_res.text}"
    crit_data = crit_res.json()
    print(f"\n--- CRITIQUE ---")
    print(json.dumps(crit_data, indent=2))

    # ── Verify idempotency: calling critique again should return existing ──────
    crit_res2 = client.post(f'/api/v1/sessions/{session_id}/critique', headers=H)
    assert crit_res2.status_code == 201
    assert crit_res2.json()['id'] == crit_data['id'], "Critique should be idempotent"
    print("\n✅ Critique is idempotent (returns same record)")

    # ── Regenerate (Generation #2) ────────────────────────────────────────────
    gen_res2 = client.post(f'/api/v1/sessions/{session_id}/generate', headers=H)
    assert gen_res2.status_code == 201
    gen_data2 = gen_res2.json()
    print(f"\n--- REGENERATED ARTWORK #2 ---")
    print(f"  ID:             {gen_data2['id']}")
    print(f"  generation_index: {gen_data2['generation_index']}")
    assert gen_data2['generation_index'] == 2, "Regeneration index should be 2"
    assert gen_data2['id'] != gen_id_1, "Regeneration should create a new record"
    print("✅ Regeneration created a new record (original preserved)")

    # ── GET /result ───────────────────────────────────────────────────────────
    result = client.get(f'/api/v1/sessions/{session_id}/result', headers=H).json()
    print(f"\n--- RESULT PAYLOAD ---")
    print(f"  session_title:        {result['session_title']}")
    print(f"  generated_artworks:   {len(result['generated_artworks'])} total")
    print(f"  latest_generated:     #{result['latest_generated']['generation_index']}")
    assert len(result['generated_artworks']) == 2, "Should have 2 generated artworks"
    print("✅ Result endpoint returns both generations, latest is #2")

    # ── Error handling: generate on non-ready session ─────────────────────────
    bad_sess = client.post('/api/v1/sessions', headers=H, json={'reference_artwork_ids': [art_id]}).json()
    bad_gen = client.post(f'/api/v1/sessions/{bad_sess["id"]}/generate', headers=H)
    assert bad_gen.status_code == 400
    print(f"\n✅ Correct 400 error on not-ready session: {bad_gen.json()['detail']}")

    print("\n=== ALL PHASE 4 TESTS PASSED ✅ ===")

if __name__ == '__main__':
    test_phase4()
