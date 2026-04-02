"""
Kademlia bootstrap node.

Acts as the well-known entry point that all DHT peers connect to when joining
the overlay. It does not cache content or serve HTTP — it only participates in
the Kademlia routing protocol so peers can discover each other.
"""

import asyncio
import os

from kademlia.network import Server


async def main() -> None:
    port = int(os.getenv("DHT_PORT", "6000"))
    ksize = int(os.getenv("DHT_KSIZE", "5"))
    alpha = int(os.getenv("DHT_ALPHA", "3"))

    server = Server(ksize=ksize, alpha=alpha)
    await server.listen(port)
    print(f"[bootstrap] DHT bootstrap node listening on UDP port {port}")

    try:
        await asyncio.Event().wait()
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
