import httpx
import json
import asyncio
import time
import os

PEER_MAP = {
    "peer-a1": "http://localhost:7001",
    "peer-a2": "http://localhost:7002",
    "peer-b1": "http://localhost:7003"
}

async def run_scenario(scenario):
    print(f"\n>>> Running Scenario: {scenario['name']}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        for step in scenario['steps']:
            action = step['action']
            peer_name = step.get('peer')
            
            if action == "fetch":
                url = f"{PEER_MAP[peer_name]}/trigger-fetch/{step['object_id']}"
                print(f"[*] {peer_name} fetching {step['object_id']}...")
                try:
                    resp = await client.get(url)
                    print(f"    Result: {resp.json()}")
                except Exception as e:
                    print(f"    Error: {e}")
            
            elif action == "kill":
                url = f"{PEER_MAP[peer_name]}/suicide"
                print(f"[!] Killing {peer_name}...")
                try:
                    await client.post(url)
                except Exception:
                    # Suicide will terminate the connection abruptly
                    pass
            
            elif action == "wait":
                secs = step['seconds']
                print(f"[.] Waiting for {secs} seconds...")
                await asyncio.sleep(secs)

async def main():
    workload_path = os.path.join(os.path.dirname(__file__), "workload.json")
    with open(workload_path, "r") as f:
        workload = json.load(f)
    
    for scenario in workload['scenarios']:
        await run_scenario(scenario)

if __name__ == "__main__":
    asyncio.run(main())
