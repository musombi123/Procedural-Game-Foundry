from __future__ import annotations
import uvicorn
from .app import HOST, PORT, pairing

if __name__ == "__main__":
    print("\\nNEXORA Desktop Device Bridge")
    print(f"Local endpoint: http://{HOST}:{PORT}")
    print(f"One-time pairing code: {pairing.code}")
    print("Keep this code private. It grants local ADB control to the paired NEXORA workspace.")
    uvicorn.run("nexora_device_bridge.app:app", host=HOST, port=PORT, log_level="warning", access_log=False)
