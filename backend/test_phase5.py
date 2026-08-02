import sys
import os
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app

client = TestClient(app)

def test_phase5():
    print("=== TESTING PHASE 5 BACKEND (SAVE, GALLERY, DELETE) ===")

    # 1. Login
    login = client.post('/api/v1/auth/login/json', json={'email': 'uploader@example.com', 'password': 'password123'})
    token = login.json()['access_token']
    H = {'Authorization': f'Bearer {token}'}

    # 2. Get reference artwork
    artworks = client.get('/api/v1/artworks').json()['artworks']
    art_id = artworks[0]['id']

    # 3. Create Session A & complete turns
    sess_res = client.post('/api/v1/sessions', headers=H, json={'reference_artwork_ids': [art_id]})
    session_id = sess_res.json()['id']
    client.post(f'/api/v1/sessions/{session_id}/messages', headers=H, json={'content': 'I love the blue color scheme'})
    client.post(f'/api/v1/sessions/{session_id}/messages', headers=H, json={'content': 'I want to place it in my bedroom for serene rest'})

    # 4. Generate artwork
    gen = client.post(f'/api/v1/sessions/{session_id}/generate', headers=H).json()
    print(f"Generated artwork URL: {gen['image_url']}")

    # 5. Save session
    save_res = client.post(f'/api/v1/sessions/{session_id}/save', headers=H)
    assert save_res.status_code == 200, f"Save failed: {save_res.text}"
    saved_sess = save_res.json()
    assert saved_sess['is_saved'] == True, "Session should be marked is_saved=True"
    print(f"Session {session_id} saved successfully! (saved_at: {saved_sess['saved_at']})")

    # 6. GET /gallery
    gallery_res = client.get('/api/v1/gallery', headers=H)
    assert gallery_res.status_code == 200
    gallery_data = gallery_res.json()
    print(f"Gallery total saved items: {gallery_data['total']}")
    assert gallery_data['total'] >= 1, "Gallery should contain at least 1 saved item"
    first_item = gallery_data['items'][0]
    print(f"Gallery Item #1: '{first_item['title']}' | Ref: {first_item['reference_artwork']['title']} | Gen: {first_item['latest_generated_artwork']['image_url']}")

    # 7. DELETE session
    del_res = client.delete(f'/api/v1/sessions/{session_id}', headers=H)
    assert del_res.status_code == 200, f"Delete failed: {del_res.text}"
    print(f"Session {session_id} deleted successfully.")

    # Verify session is gone from DB
    get_gone = client.get(f'/api/v1/sessions/{session_id}', headers=H)
    assert get_gone.status_code == 404, "Deleted session should return 404"

    print("=== PHASE 5 BACKEND TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    test_phase5()
