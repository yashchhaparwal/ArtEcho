import sys
import os
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app

client = TestClient(app)

def run_test():
    print("=== TESTING PHASE 3 CONVERSATION ENGINE ===")

    # 1. Login or Signup test user
    login_res = client.post('/api/v1/auth/login/json', json={'email': 'uploader@example.com', 'password': 'password123'})
    if login_res.status_code != 200:
        client.post('/api/v1/auth/signup', json={'email': 'uploader@example.com', 'password': 'password123', 'name': 'Art Lover'})
        login_res = client.post('/api/v1/auth/login/json', json={'email': 'uploader@example.com', 'password': 'password123'})

    token = login_res.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    # 2. Get an artwork ID from library
    artworks_res = client.get('/api/v1/artworks')
    artworks = artworks_res.json()['artworks']
    starry_night = next(a for a in artworks if 'Starry Night' in a['title'])
    print(f"Selected reference artwork: '{starry_night['title']}' by {starry_night['artist']} (ID: {starry_night['id']})")

    # 3. Create a new ChatSession
    create_session_res = client.post(
        '/api/v1/sessions',
        headers=headers,
        json={'reference_artwork_ids': [starry_night['id']]}
    )
    assert create_session_res.status_code == 201, f"Session creation failed: {create_session_res.text}"
    session_data = create_session_res.json()
    session_id = session_data['id']
    print(f"\n[Session Created] ID: {session_id}")
    print(f"Initial Assistant Opening Message:\n  Muse: {session_data['messages'][0]['content']}\n")

    # 4. Simulate conversation turns
    user_turns = [
        "I'm drawn to the swirling deep blue night sky and how the glowing yellow stars pop against the darkness.",
        "I want to place this new piece on my bedroom wall to create a serene, dreamy feeling before going to sleep."
    ]

    for turn_idx, user_input in enumerate(user_turns, start=1):
        print(f"--- TURN {turn_idx} ---")
        print(f"User: {user_input}")

        msg_res = client.post(
            f'/api/v1/sessions/{session_id}/messages',
            headers=headers,
            json={'content': user_input}
        )
        assert msg_res.status_code == 200, f"Message creation failed: {msg_res.text}"
        assistant_msg = msg_res.json()
        print(f"Muse: {assistant_msg['content']}\n")

        # Fetch updated session state
        sess_get = client.get(f'/api/v1/sessions/{session_id}', headers=headers).json()
        print(f"Running Context Summary:\n{sess_get['context_summary']}")
        print(f"Ready to Generate: {sess_get['is_ready_to_generate']}\n")

    print("=== CONVERSATION TEST COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_test()
