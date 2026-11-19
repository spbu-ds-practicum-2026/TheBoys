"""
Failure Recovery & Node Scaling Tests (TR: Сценарии 5, 6, «Обнаружение отказов», «Взаимозаменяемые узлы приложения»,
План тестирования строки 501-506).

Addresses Oleg's review feedback:
1. Node heartbeat expiration vs session ping freshness:
   Clearly distinguishes node availability (last_heartbeat <= 15s) from session freshness (last_seen <= 30s).
   If a node crashes silently (heartbeat > 15s ago), even a freshly pinged session on that node
   MUST NOT be reported as online and MUST NOT be targeted for delivery.
2. Crash recovery & lost ACK handling across independent nodes:
   Simulates network failure / node crash where client sends message to Node 1, message is committed in DB,
   but connection drops before client receives ACK. Client fails over to Node 2, resends with same client_msg_id,
   receives ACK with seq=1, and history sync confirms zero duplicate messages.
3. Dynamic node addition:
   Tests registering an independent working application node instance dynamically into the cluster
   and serving user traffic without modifying configuration or restarting other nodes.
"""

import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

# Ensure test secrets and proxy settings are set before importing main
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from services.app.auth import hash_password
from services.app.db import db, Database, clean_postgres_dsn
from services.app.main import (
    app as app_node1,
    create_app,
    sign_session_cookie,
    COOKIE_NAME,
    INTERNAL_SECRET,
    NODE_ID as NODE1_ID,
)

ORIGIN = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_database_state():
    db.memory.clear()
    db.enable_in_memory = True
    app_node1.state.enable_persistence = True
    app_node1.state.crashed = False
    now = datetime.now(timezone.utc)
    db.memory.node_registry[NODE1_ID] = {
        "node_id": NODE1_ID,
        "role": "app",
        "endpoint_url": f"http://{NODE1_ID}:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    yield
    app_node1.state.crashed = False
    app_node1.state.enable_persistence = False
    db.enable_in_memory = False
    db.memory.clear()


def make_client_for_user(user_id: int, target_app=app_node1) -> TestClient:
    client = TestClient(target_app, follow_redirects=False)
    cookie_val = sign_session_cookie(user_id)
    client.cookies.set(COOKIE_NAME, cookie_val)
    return client


def open_ws(client: TestClient):
    cookie_val = client.cookies.get(COOKIE_NAME)
    headers = {"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}={cookie_val}"}
    return client.websocket_connect("/ws", headers=headers)


# ---------------------------------------------------------------------------
# Test 1: Node Heartbeat Expiry vs Session Ping Freshness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_node_heartbeat_timeout_drops_online_status_regardless_of_session_freshness():
    """
    TR: Раздел «Обнаружение отказов» & Технический сценарий 5, п. 6:
    Distinguishes node heartbeat freshness (<= 15 seconds) from session ping freshness (<= 30 seconds).

    Scenario 1:
      - Node is alive (heartbeat 5s ago <= 15s)
      - Session is alive (last_seen 5s ago <= 30s)
      -> User IS online, session IS included in active sessions and deliverable.

    Scenario 2 (Silent node crash):
      - Session is fresh (last_seen 2s ago, browser still open!)
      - Node crashed silently: last_heartbeat 20s ago (> 15s threshold)
      -> User MUST NOT be reported as online!
      -> Stale node MUST NOT receive message deliveries.

    Scenario 3 (Session expiry on healthy node):
      - Node is alive (heartbeat 2s ago)
      - Session is stale (last_seen 35s ago > 30s threshold)
      -> User MUST NOT be reported as online.
    """
    u1 = await db.create_user("charlie", hash_password("pass"))
    user_id = u1["id"]
    conn_id = uuid4()
    now = datetime.now(timezone.utc)

    # 1. Healthy state: both node heartbeat and session ping are fresh
    db.memory.node_registry["app-cluster-node"] = {
        "node_id": "app-cluster-node",
        "role": "app",
        "endpoint_url": "http://app-cluster-node:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    db.memory.sessions[conn_id] = {
        "connection_id": conn_id,
        "user_id": user_id,
        "node_id": "app-cluster-node",
        "last_seen": now,
    }

    # Verify user is online and session is discoverable
    assert await db.get_user_online_status(user_id) is True
    active_sessions = await db.get_active_sessions_for_users([user_id])
    assert len(active_sessions) == 1
    assert active_sessions[0]["connection_id"] == conn_id

    # 2. Silent node crash: session ping is fresh (2s ago), but node heartbeat expired (20s ago > 15s)
    db.memory.sessions[conn_id]["last_seen"] = now - timedelta(seconds=2)
    db.memory.node_registry["app-cluster-node"]["last_heartbeat"] = now - timedelta(seconds=20)

    # CRITICAL: Stale node heartbeat must immediately drop online status!
    is_online_after_node_crash = await db.get_user_online_status(user_id)
    assert is_online_after_node_crash is False, (
        "User on a node whose heartbeat expired (>15s) must NOT be reported as online even if session is fresh!"
    )

    # Stale node sessions must be excluded from message delivery routing
    sessions_after_crash = await db.get_active_sessions_for_users([user_id])
    assert sessions_after_crash == [], "Crashed node session must not be returned for message delivery!"

    # Endpoint must return None
    endpoint_after_crash = await db.get_node_endpoint("app-cluster-node")
    assert endpoint_after_crash is None, "Crashed node endpoint must not be returned!"

    # 3. Healthy node, but idle/expired session (35s ago > 30s)
    db.memory.node_registry["app-cluster-node"]["last_heartbeat"] = now
    db.memory.sessions[conn_id]["last_seen"] = now - timedelta(seconds=35)

    assert await db.get_user_online_status(user_id) is False
    assert await db.get_active_sessions_for_users([user_id]) == []


# ---------------------------------------------------------------------------
# Test 2: Crash Failover, Lost ACK Recovery & Reconnection Across Nodes
# ---------------------------------------------------------------------------

def test_reconnection_and_lost_ack_recovery_across_independent_nodes():
    """
    TR: Технический сценарий 6 «Потеря соединения» & Пользовательский сценарий 7:
    Simulates:
    1. Alice connects to Node 1 via WebSocket.
    2. Alice sends a message with client_msg_id.
    3. Message is stored in shared DB with seq=1.
    4. Node 1 abruptly crashes / connection drops BEFORE client receives the ACK.
    5. Node 1 is stopped and can no longer serve traffic.
    6. Client detects disconnect, reconnects to living Node 2 (an independent app instance with distinct NODE_ID).
    7. Client re-sends unacknowledged message with the exact same client_msg_id to Node 2.
    8. Node 2 processes retry idempotently: returns ACK with existing seq=1, does NOT allocate a new seq.
    9. Client syncs history via Node 2: confirms exactly 1 message exists in dialogue (no duplicates!).
    """
    node2_id = "app-node-2"
    app_node2 = create_app(node2_id)
    app_node2.state.enable_persistence = True

    now = datetime.now(timezone.utc)
    db.memory.node_registry[node2_id] = {
        "node_id": node2_id,
        "role": "app",
        "endpoint_url": f"http://{node2_id}:8000",
        "last_heartbeat": now,
        "status": "alive",
    }

    # Two distinct clients for two independent application node instances
    client1 = TestClient(app_node1, follow_redirects=False)
    client2 = TestClient(app_node2, follow_redirects=False)

    alice = client1.post("/api/register", json={"login": "alice_failover", "password": "password"}).json()["user"]
    bob = client2.post("/api/register", json={"login": "bob_failover", "password": "password"}).json()["user"]

    conv_id = client1.get("/api/users", params={"login": "bob_failover"}).json()["conversation"]["conversation_id"]

    lost_ack_msg_id = str(uuid4())

    try:
        # Step 1: Alice sends message to Node 1
        with open_ws(client1) as ws_node1:
            # Drain initial sync
            ws_node1.send_text('{"type": "ping"}')
            _ = ws_node1.receive_json()

            # Send message
            ws_node1.send_text(
                f'{{"type": "send_message", "client_msg_id": "{lost_ack_msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Сообщение с потерянным ACK"}}}}'
            )

            # Allow server to commit message to DB before connection abruptly drops
            time.sleep(0.1)
            # Client disconnects without reading ACK (lost ACK scenario)

        # Step 1b: Node 1 abruptly crashes / stops serving traffic
        db.memory.node_registry[NODE1_ID]["status"] = "dead"
        db.memory.node_registry[NODE1_ID]["last_heartbeat"] = now - timedelta(seconds=60)
        app_node1.state.crashed = True

        # Verify that Node 1 is truly down and can no longer be connected to:
        # 1. New WebSocket connection to Node 1 must be rejected/closed immediately
        with pytest.raises(Exception):
            with open_ws(client1) as ws_dead:
                ws_dead.send_text('{"type": "ping"}')
                ws_dead.receive_json()

        # 2. HTTP requests to Node 1 return 503 NODE_UNAVAILABLE
        health_dead = client1.get("/health")
        assert health_dead.status_code == 503
        assert health_dead.json()["code"] == "NODE_UNAVAILABLE"

        # Step 2: Bob on Node 2 sends a reply while Alice is reconnecting
        with open_ws(client2) as ws_bob:
            ws_bob.send_text('{"type": "ping"}')
            _ = ws_bob.receive_json()

            bob_msg_id = str(uuid4())
            ws_bob.send_text(
                f'{{"type": "send_message", "client_msg_id": "{bob_msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Ответ от Боба"}}}}'
            )
            ack_bob = ws_bob.receive_json()
            assert ack_bob["type"] == "ack"
            assert ack_bob["seq"] == 2

        # Step 3: Alice reconnects to living Node 2 (app_node2) and resends unacknowledged message
        client1_node2 = make_client_for_user(alice["id"], target_app=app_node2)
        with open_ws(client1_node2) as ws_reconnected:
            # Re-send the unacknowledged message with the same client_msg_id to Node 2
            ws_reconnected.send_text(
                f'{{"type": "send_message", "client_msg_id": "{lost_ack_msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Сообщение с потерянным ACK"}}}}'
            )

            # Node 2 must return ACK with the original seq=1 without consuming a new sequence number!
            ack_resend = ws_reconnected.receive_json()
            assert ack_resend["type"] == "ack"
            assert ack_resend["seq"] == 1, "Duplicate retry after lost ACK must return original seq=1!"
            assert ack_resend["client_msg_id"] == lost_ack_msg_id

            # Alice confirms read position up to seq=1
            ws_reconnected.send_text(f'{{"type": "read", "conversation_id": {conv_id}, "up_to_seq": 1}}')
            read_ack = ws_reconnected.receive_json()
            assert read_ack["type"] == "read_ack"
            assert read_ack["last_read_seq"] == 1
            assert read_ack["unread_count"] == 1  # Only Bob's reply (seq=2) is unread

            # Alice syncs history to retrieve all dialogue messages via Node 2
            ws_reconnected.send_text(f'{{"type": "sync", "conversation_id": {conv_id}, "since_seq": 0, "limit": 10}}')
            history = ws_reconnected.receive_json()
            assert history["type"] == "history"
            messages = history["messages"]

            # Exactly 2 messages in dialogue: Alice's seq=1 and Bob's seq=2. No duplicate of Alice's message!
            assert len(messages) == 2, f"Expected exactly 2 messages in history, got {len(messages)}"
            assert messages[0]["seq"] == 1
            assert messages[0]["client_msg_id"] == lost_ack_msg_id
            assert messages[0]["payload"]["text"] == "Сообщение с потерянным ACK"
            assert messages[1]["seq"] == 2
            assert messages[1]["payload"]["text"] == "Ответ от Боба"
    finally:
        app_node1.state.crashed = False


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL not running (run with DATABASE_URL or in docker)")
@pytest.mark.asyncio
async def test_live_postgres_lost_ack_failover_across_independent_nodes():
    """
    TR: Технический сценарий 6 «Потеря соединения» & План тестирования (строка 502):
    Tests lost ACK failover across two independent node IDs against a real shared PostgreSQL database.
    1. Node 1 commits message with client_msg_id to live PostgreSQL.
    2. Node 1 crashes / fails before ACK is delivered to client.
    3. Client reconnects to Node 2 (with distinct NODE_ID) connected to the same PostgreSQL DB.
    4. Client resends unacknowledged message with same client_msg_id.
    5. Node 2 calls live Database.store_message, which detects duplicate via FOR UPDATE lock
       and returns existing seq without consuming a new sequence number.
    6. Verifies exactly 1 row exists in messages table for this message and conversations.last_seq == 1.
    """
    dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
    live_db1 = Database()
    live_db2 = Database()
    await live_db1.connect(dsn)
    await live_db2.connect(dsn)

    try:
        u1 = await live_db1.create_user(f"alice_pg_fail_{uuid4().hex[:8]}", "dummyhash")
        u2 = await live_db1.create_user(f"bob_pg_fail_{uuid4().hex[:8]}", "dummyhash")
        conv = await live_db1.find_or_create_conversation(u1["id"], u2["id"])
        conv_id = conv["id"]

        lost_ack_id = uuid4()

        # Step 1: Node 1 stores message
        seq1, created_at1, is_new1, members1 = await live_db1.store_message(
            conversation_id=conv_id,
            sender_id=u1["id"],
            kind="text",
            payload={"text": "PG message with lost ACK"},
            client_msg_id=lost_ack_id,
        )
        assert is_new1 is True
        assert seq1 == 1

        # Step 2: Node 1 crashes / disconnects
        await live_db1.disconnect()

        # Step 3: Node 2 processes the retry
        seq2, created_at2, is_new2, members2 = await live_db2.store_message(
            conversation_id=conv_id,
            sender_id=u1["id"],
            kind="text",
            payload={"text": "PG message with lost ACK"},
            client_msg_id=lost_ack_id,
        )
        assert is_new2 is False, "Retry must not be treated as a new message"
        assert seq2 == 1, "Retry must return original seq=1"

        # Step 4: Verify PostgreSQL table state directly
        async with live_db2.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, seq, client_msg_id FROM messages WHERE conversation_id = $1", conv_id)
            assert len(rows) == 1
            assert rows[0]["seq"] == 1
            assert rows[0]["client_msg_id"] == lost_ack_id

            final_last_seq = await conn.fetchval("SELECT last_seq FROM conversations WHERE id = $1", conv_id)
            assert final_last_seq == 1
    finally:
        if live_db1.is_connected:
            await live_db1.disconnect()
        if live_db2.is_connected:
            await live_db2.disconnect()


# ---------------------------------------------------------------------------
# Test 3: Dynamic Node Addition & Request Handling Without Restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dynamic_node_addition_and_traffic_handling():
    """
    TR: Раздел «Взаимозаменяемые узлы приложения» & План тестирования (строка 503):
    «Тест добавления нового узла приложения».
    A real additional application instance is launched on a local port.
    The new instance registers ITSELF in node_registry on startup via lifespan,
    serves client requests returning its own node_id, and handles traffic
    without restarting existing nodes or load balancers.
    """
    # 1. Allocate a free local port for the new node
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    new_node_id = "app-node-dynamic-2"
    endpoint_url = f"http://127.0.0.1:{free_port}"

    # Create instance with lifespan enabled so it registers itself automatically
    new_app = create_app(new_node_id, endpoint_url=endpoint_url)
    new_app.state.enable_persistence = True

    # 2. Run the new instance in a background thread
    config = uvicorn.Config(
        new_app,
        host="127.0.0.1",
        port=free_port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        # Wait for the new instance to become healthy
        start_time = time.time()
        ready = False
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            while time.time() - start_time < 5.0:
                try:
                    resp = client.get(f"{endpoint_url}/health")
                    if resp.status_code == 200:
                        ready = True
                        break
                except Exception:
                    time.sleep(0.05)

        assert ready, f"Dynamic app node failed to start on port {free_port}"

        # 3. Verify that the new node registered ITSELF in node_registry on startup (via lifespan)
        # without the test manually calling db.register_node!
        node_entry = db.memory.node_registry.get(new_node_id)
        assert node_entry is not None, f"Node {new_node_id} must self-register in node_registry upon startup!"
        assert node_entry["endpoint_url"] == endpoint_url
        assert node_entry["status"] == "alive"

        # 4. Verify the new instance returns its own node_id in /health
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            health_resp = client.get(f"{endpoint_url}/health")
            assert health_resp.status_code == 200
            health_data = health_resp.json()
            assert health_data["status"] == "ok"
            assert health_data["node_id"] == new_node_id, (
                f"Expected health check to return node_id='{new_node_id}', got '{health_data.get('node_id')}'"
            )

            # 5. Verify the new node serves client registration requests directly
            reg_resp = client.post(
                f"{endpoint_url}/api/register",
                json={"login": "dynamic_scaled_user", "password": "password123"},
            )
            assert reg_resp.status_code == 201
            assert reg_resp.json()["user"]["login"] == "dynamic_scaled_user"

        # 6. When node heartbeat expires (>15s), it is excluded automatically
        old_time = datetime.now(timezone.utc) - timedelta(seconds=20)
        db.memory.node_registry[new_node_id]["last_heartbeat"] = old_time
        expired_endpoint = await db.get_node_endpoint(new_node_id)
        assert expired_endpoint is None, "Expired node must be excluded from routing"

    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


def test_nginx_dynamic_scaling_discovery_and_failover_coverage():
    """
    TR: Раздел «Взаимозаменяемые узлы приложения» & План тестирования (строка 503):
    «Тест добавления нового узла приложения».
    Verifies Nginx dynamic discovery of scaled app containers without reloading Nginx.
    1. Checks initial count of running app containers in docker compose (e.g. 1 instance).
    2. Scales up app to initial_count + 1 (e.g. 1 -> 2) without restarting Nginx.
    3. Verifies the new node self-registers in PostgreSQL node_registry.
    4. Verifies Nginx distributes requests to both instances, observing the new node_id
       in responses via Nginx without reloading Nginx.
    """
    import subprocess
    nginx_url = os.getenv("NGINX_URL", "http://localhost:80")

    # 1. Precondition checks
    try:
        with httpx.Client(timeout=3.0, trust_env=False) as client:
            resp = client.get(f"{nginx_url}/nginx-health")
            if resp.status_code != 200:
                pytest.skip(f"Nginx is not healthy at {nginx_url} (HTTP {resp.status_code})")
    except Exception as e:
        pytest.skip(f"Nginx reverse proxy is not reachable at {nginx_url}: {e}")

    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            pytest.skip("Docker Compose CLI check failed")
    except Exception as e:
        pytest.skip(f"Docker Compose not found: {e}")

    ps_proc = subprocess.run(["docker", "compose", "ps", "-q", "app"], capture_output=True, text=True, timeout=10)
    if ps_proc.returncode != 0:
        pytest.skip("docker compose ps failed")

    initial_cids = set(cid.strip() for cid in ps_proc.stdout.splitlines() if cid.strip())
    initial_count = len(initial_cids)
    if initial_count < 1:
        pytest.skip("No running app instances found in docker compose stack")

    with httpx.Client(timeout=5.0, trust_env=False) as client:
        try:
            # 1. Scale up to initial_count + 1 (ensuring 1 -> 2 or N -> N+1) without reloading Nginx
            scaled_target = initial_count + 1
            scale_up = subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app={scaled_target}", "--no-recreate"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert scale_up.returncode == 0, f"Failed to scale app to {scaled_target} instances"

            # 2. Identify the newly added container independently
            ps_after = subprocess.run(["docker", "compose", "ps", "-q", "app"], capture_output=True, text=True, timeout=10)
            current_cids = set(cid.strip() for cid in ps_after.stdout.splitlines() if cid.strip())
            added_cids = current_cids - initial_cids
            assert len(added_cids) == 1, f"Expected exactly 1 added app container, found: {added_cids}"
            added_cid = list(added_cids)[0]

            # 3. Determine the node_id of the added container independently of Nginx responses
            env_proc = subprocess.run(
                ["docker", "exec", added_cid, "sh", "-c", "echo -n ${NODE_ID:-$(hostname)}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if env_proc.returncode == 0 and env_proc.stdout.strip():
                added_node_id = env_proc.stdout.strip()
            else:
                insp_proc = subprocess.run(
                    ["docker", "inspect", "--format", "{{.Config.Hostname}}", added_cid],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                added_node_id = insp_proc.stdout.strip()

            assert added_node_id, f"Could not determine node_id for added container {added_cid}"

            # 4. Verify its self-registration in PostgreSQL node_registry (status = 'alive')
            # Extract POSTGRES_USER and POSTGRES_DB dynamically from the container environment
            pg_env_proc = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres", "sh", "-c", "echo -n ${POSTGRES_USER:-theboys_user},${POSTGRES_DB:-theboys}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if pg_env_proc.returncode != 0:
                raise RuntimeError(
                    f"Failed to inspect PostgreSQL container environment (exit {pg_env_proc.returncode}): {pg_env_proc.stderr.strip()}"
                )
            pg_user, pg_db = pg_env_proc.stdout.strip().split(",", 1)

            registered = False
            last_conn_error = None
            query_stdout = ""
            for _ in range(30):
                psql_res = subprocess.run(
                    [
                        "docker", "compose", "exec", "-T", "postgres",
                        "psql", "-U", pg_user, "-d", pg_db, "-tAc",
                        f"SELECT status FROM node_registry WHERE node_id = '{added_node_id}';",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if psql_res.returncode != 0:
                    last_conn_error = psql_res.stderr.strip() or f"psql exited with code {psql_res.returncode}"
                else:
                    last_conn_error = None
                    query_stdout = psql_res.stdout.strip()
                    if "alive" in query_stdout:
                        registered = True
                        break
                time.sleep(0.5)

            if last_conn_error:
                raise RuntimeError(f"PostgreSQL connection error while querying node_registry: {last_conn_error}")

            assert registered, (
                f"Added node {added_node_id} did not self-register in PostgreSQL node_registry (query output: '{query_stdout}')"
            )

            # 5. Poll /health through Nginx without restarting/reloading until the added_node_id is returned
            observed_added_node = False
            start_poll = time.time()
            while time.time() - start_poll < 35:
                try:
                    r = client.get(f"{nginx_url}/health")
                    if r.status_code == 200:
                        nid = r.json().get("node_id")
                        if nid == added_node_id:
                            observed_added_node = True
                            break
                except Exception:
                    pass
                time.sleep(0.1)

            assert observed_added_node, (
                f"Expected Nginx to route traffic to added node {added_node_id} without reload, "
                f"but /health did not return this node_id within timeout"
            )

        finally:
            # Restore initial scale
            subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app={initial_count}", "--no-recreate"],
                capture_output=True,
                text=True,
                timeout=45,
            )
