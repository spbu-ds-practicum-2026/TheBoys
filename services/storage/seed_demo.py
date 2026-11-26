"""Install the bundled demo track after starting Compose."""
import asyncio
import hashlib
import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx


async def main():
    audio = Path(__file__).with_name("demo.mp3").read_bytes()
    track = UUID(bytes=hashlib.sha256(audio).digest()[:16])
    node = os.environ["NODE_ID"]
    endpoint = os.environ["NODE_ENDPOINT_URL"]
    headers = {"X-Internal-Secret": os.environ["INTERNAL_SECRET"]}
    async with httpx.AsyncClient(headers=headers) as client:
        url = f"{endpoint}/blobs/{track}"
        (await client.put(url, content=audio)).raise_for_status()
        part = await client.get(url, headers={"Range": "bytes=1000-1999"})
        if part.status_code != 206 or part.content != audio[1000:2000]:
            raise RuntimeError("Storage did not return the requested MP3 bytes")

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO tracks (id, title, artist, duration_s, size_bytes)
                   VALUES ($1, 'Boysic Demo', 'Boysic', 24, $2)
                   ON CONFLICT (id) DO NOTHING""", track, len(audio),
            )
            await conn.execute(
                """INSERT INTO replicas (track_id, node_id) VALUES ($1, $2)
                   ON CONFLICT (track_id, node_id) DO UPDATE SET status = 'active'""",
                track, node,
            )
    finally:
        await conn.close()
    print(f"Boysic Demo: {track} on {node}, Range verified, catalog ready")


if __name__ == "__main__":
    asyncio.run(main())
