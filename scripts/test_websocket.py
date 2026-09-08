import asyncio
import json
import requests
import websockets

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/twin/3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2"

async def test_websocket():
    print(f"Connecting to WebSocket endpoint {WS_URL}...")
    async with websockets.connect(WS_URL) as ws:
        # Receive initial state event
        init_msg = await ws.recv()
        print("Received Initial WebSocket Message:")
        print(json.loads(init_msg))

        # Send test ingestion trigger over HTTP
        print("\nTriggering live sensor ingestion POST /ingest...")
        requests.post(f"{BASE_URL}/ingest", json={
            "patient_id": "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2",
            "hr": 145.0,
            "spo2": 87.0,
            "temp": 39.5,
            "bp_sys": 170,
            "bp_dia": 105
        })

        # Listen for real-time broadcast event over WebSocket
        broadcast_msg = await ws.recv()
        print("\nSUCCESS: Real-time WebSocket Broadcast Received!")
        print(json.dumps(json.loads(broadcast_msg), indent=2))

if __name__ == "__main__":
    asyncio.run(test_websocket())
