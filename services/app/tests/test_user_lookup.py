"""Поиск собеседника по логину и открытие диалога: GET /api/users?login=… (ТР, технический сценарий 4, п. 1)."""
import pytest
from fastapi.testclient import TestClient

from services.app.dev import server


@pytest.fixture(autouse=True)
def clean_state():
    server.users.clear()
    server.conversations.clear()
    server.connections.clear()
    yield


def make_user(login: str) -> tuple[TestClient, dict]:
    client = TestClient(server.app, follow_redirects=False)
    response = client.post("/api/register", json={"login": login, "password": "secret"})
    assert response.status_code == 201, response.text
    return client, response.json()["user"]


def lookup(client: TestClient, login: str):
    return client.get("/api/users", params={"login": login})


@pytest.fixture
def pair():
    alice, alice_user = make_user("alice")
    bob, bob_user = make_user("bob")
    return alice, alice_user, bob, bob_user


def test_exact_login_returns_peer_and_opens_conversation(pair):
    alice, _, _, bob_user = pair
    response = lookup(alice, "bob")
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": bob_user["id"], "login": "bob"}
    conversation = body["conversation"]
    assert set(conversation) == {"conversation_id", "peer", "last_seq", "unread_count"}
    assert conversation["peer"] == body["user"]
    assert conversation["last_seq"] == 0 and conversation["unread_count"] == 0
    assert len(server.conversations) == 1


def test_lookup_ignores_case_and_surrounding_spaces(pair):
    alice, _, _, bob_user = pair
    for login in ("BOB", "  Bob  "):
        response = lookup(alice, login)
        assert response.status_code == 200, login
        assert response.json()["user"]["id"] == bob_user["id"]
    assert len(server.conversations) == 1


def test_part_of_login_does_not_match(pair):
    alice, *_ = pair
    make_user("bobby")
    response = lookup(alice, "bo")
    assert response.status_code == 404 and response.json()["code"] == "USER_NOT_FOUND"
    assert lookup(alice, "bob").json()["user"]["login"] == "bob"  # именно bob, а не bobby


def test_unknown_login_is_404_and_creates_nothing(pair):
    alice, *_ = pair
    response = lookup(alice, "nobody")
    assert response.status_code == 404 and response.json()["code"] == "USER_NOT_FOUND"
    assert server.conversations == {}


@pytest.mark.parametrize("login", ["", "   ", "alice", "ALICE"])
def test_empty_or_own_login_is_rejected(pair, login):
    alice, *_ = pair
    response = lookup(alice, login)
    assert response.status_code == 422 and response.json()["code"] == "INVALID_INPUT"
    assert server.conversations == {}


def test_missing_login_parameter_is_rejected(pair):
    alice, *_ = pair
    assert alice.get("/api/users").status_code == 422
    assert server.conversations == {}


def test_same_pair_always_gets_one_conversation(pair):
    alice, alice_user, bob, _ = pair
    first = lookup(alice, "bob").json()["conversation"]["conversation_id"]
    again = lookup(alice, "bob").json()["conversation"]["conversation_id"]
    from_bob = lookup(bob, "alice").json()["conversation"]
    assert first == again == from_bob["conversation_id"]
    assert from_bob["peer"] == {"id": alice_user["id"], "login": "alice"}
    assert len(server.conversations) == 1


def test_lookup_requires_login_and_is_not_cached(pair):
    alice, *_ = pair
    assert TestClient(server.app).get("/api/users", params={"login": "bob"}).status_code == 401
    assert lookup(alice, "bob").headers["Cache-Control"] == "no-store"


def test_conversation_list_returns_same_object(pair):
    alice, *_ = pair
    opened = lookup(alice, "bob").json()["conversation"]
    assert alice.get("/api/conversations").json() == [opened]


def test_post_conversations_is_removed(pair):
    alice, _, _, bob_user = pair
    response = alice.post("/api/conversations", json={"peer_id": bob_user["id"]})
    assert response.status_code in (404, 405)
    assert server.conversations == {}
