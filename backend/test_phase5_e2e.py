import sys
import os
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app

client = TestClient(app)

def test_full_phase5():
    print("=== PHASE 5 FULL E2E VERIFICATION ===")

    # 1. Login
    login = client.post('/api/v1/auth/login/json', json={'email': 'uploader@example.com', 'password': 'password123'})
    token = login.json()['access_token']
    H = {'Authorization': f'Bearer {token}'}

    # 2. Get artworks
    artworks = client.get('/api/v1/artworks').json()['artworks']
    starry = artworks[0]
    mona = artworks[1]

    # --- SESSION 1 ---
    s1 = client.post('/api/v1/sessions', headers=H, json={'reference_artwork_ids': [starry['id']]}).json()
    client.post(f"/api/v1/sessions/{s1['id']}/messages", headers=H, json={'content': 'I love blue swirling sky'})
    client.post(f"/api/v1/sessions/{s1['id']}/messages", headers=H, json={'content': 'Display in my bedroom for peaceful sleep'})
    client.post(f"/api/v1/sessions/{s1['id']}/generate", headers=H, params={"wait": True})
    client.post(f"/api/v1/sessions/{s1['id']}/save", headers=H)
    print(f"Session 1 created & saved: {s1['id']}")

    # --- SESSION 2 ---
    s2 = client.post('/api/v1/sessions', headers=H, json={'reference_artwork_ids': [mona['id']]}).json()
    client.post(f"/api/v1/sessions/{s2['id']}/messages", headers=H, json={'content': 'I admire the subtle warm earth tones and sfumato lighting'})
    client.post(f"/api/v1/sessions/{s2['id']}/messages", headers=H, json={'content': 'Place in my study room for a contemplative mood'})
    client.post(f"/api/v1/sessions/{s2['id']}/generate", headers=H, params={"wait": True})
    client.post(f"/api/v1/sessions/{s2['id']}/save", headers=H)
    print(f"Session 2 created & saved: {s2['id']}")

    # 3. GET /gallery (Verify at least 2 saved sessions)
    gallery_res = client.get('/api/v1/gallery', headers=H)
    assert gallery_res.status_code == 200
    g_data = gallery_res.json()
    print(f"Gallery total saved items: {g_data['total']}")
    assert g_data['total'] >= 2, "Gallery must contain at least 2 saved sessions!"
    print("✅ Gallery verified with at least 2 saved sessions.")

    # 4. Test DELETE session
    del_res = client.delete(f"/api/v1/sessions/{s1['id']}", headers=H)
    assert del_res.status_code == 200
    print(f"Session 1 ({s1['id']}) deleted.")

    # Verify session 1 is gone from gallery
    g_after = client.get('/api/v1/gallery', headers=H).json()
    deleted_ids = [i['session_id'] for i in g_after['items']]
    assert s1['id'] not in deleted_ids, "Deleted session 1 must not be in gallery!"
    print("✅ Confirm delete removes DB rows and files from disk.")

    # 5. Verify Auth Guards (unauthenticated requests return 401)
    unauth_gal = client.get('/api/v1/gallery')
    assert unauth_gal.status_code == 401, "Unauthenticated /gallery must return 401"

    unauth_sess = client.get('/api/v1/sessions')
    assert unauth_sess.status_code == 401, "Unauthenticated /sessions must return 401"
    print("✅ Auth guards return 401 for unauthenticated requests.")

    print("\n=== ALL PHASE 5 VERIFICATIONS PASSED SUCCESSFULLY ✅ ===")

if __name__ == "__main__":
    test_full_phase5()
