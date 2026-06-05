import asyncio
import sys
import os
import math
import struct
import subprocess
import time
import logging
import socket
from dotenv import load_dotenv, find_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("speaker_microservice.test")

# Add the project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def sine_wave_generator(sample_rate=44100, duration=2.0, freq=440.0, channels=1):
    """
    Generate mathematical pure sine wave audio chunks.
    """
    num_samples = int(sample_rate * duration)
    chunk_size = 2048 
    
    for i in range(0, num_samples, chunk_size):
        chunk_bytes = bytearray()
        for j in range(chunk_size):
            if i + j >= num_samples:
                break
            
            # Pure sine tone
            val = int(math.sin(2 * math.pi * freq * (i + j) / sample_rate) * 20000) # Slightly reduced amplitude for testing comfort
            packed_value = struct.pack('<h', val)
            
            for _ in range(channels):
                chunk_bytes.extend(packed_value)
        
        yield bytes(chunk_bytes)
        # Yield control to match physical playback speed
        await asyncio.sleep((chunk_size / sample_rate) * 0.8)

def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            return True
    except socket.error:
        return False

async def run_test():
    # 1. Load config
    dotenv_path = find_dotenv('.env')
    if dotenv_path:
        load_dotenv(dotenv_path)
    
    host = os.getenv("SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SERVICE_PORT", "8003"))
    
    logger.info(f"Targeting server on {host}:{port}")

    # 2. Spin up Uvicorn Speaker Microservice in its own directory
    logger.info("Booting Uvicorn Speaker Microservice in background...")
    python_executable = sys.executable
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    server_process = subprocess.Popen(
        [python_executable, "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=project_root
    )
    if server_process.stdout is None:
        raise RuntimeError("Server process stdout pipe was not created.")
    server_stdout = server_process.stdout
    
    # Start a thread to read and print server logs in real-time
    def log_streamer():
        for line in iter(server_stdout.readline, ''):
            sys.stdout.write(f"[Server] {line}")
            sys.stdout.flush()
            
    import threading
    log_thread = threading.Thread(target=log_streamer, daemon=True)
    log_thread.start()
    
    # Wait until the port opens or the process dies
    attempts = 0
    max_attempts = 30
    server_healthy = False
    
    while attempts < max_attempts:
        if server_process.poll() is not None:
            logger.error("Server background process failed to start!")
            sys.exit(1)
            
        if is_port_open(host, port):
            server_healthy = True
            logger.info("Server is up and listening!")
            break
            
        await asyncio.sleep(0.2)
        attempts += 1
        
    if not server_healthy:
        logger.error("Timed out waiting for server to startup.")
        server_process.terminate()
        sys.exit(1)

    # 3. Query health check first
    import urllib.request
    import json
    
    health_url = f"http://{host}:{port}/health"
    logger.info(f"Querying health endpoint: {health_url}")
    try:
        with urllib.request.urlopen(health_url, timeout=2.0) as response:
            health_data = json.loads(response.read().decode())
            logger.info(f"Health response: {health_data}")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        server_process.terminate()
        sys.exit(1)

    # Import websockets inside test loop to prevent import errors at load time
    import websockets
    from websockets.typing import Origin
    
    uri = f"ws://{host}:{port}/play/ws?sample_rate=44100&channels=1"
    logger.info(f"Connecting to WebSocket: {uri}")
    
    try:
        async with websockets.connect(uri, origin=Origin("http://127.0.0.1:8003")) as ws:
            logger.info("WebSocket connection established! Beginning sound playback...")
            logger.info("🎧 Playing 2 seconds of 440Hz Sine Wave...")
            
            logger.info(f"Stream event: {json.loads(await ws.recv())}")

            chunk_count = 0
            async for chunk in sine_wave_generator(sample_rate=44100, duration=2.0, freq=440.0, channels=1):
                await ws.send(chunk)
                event = json.loads(await ws.recv())
                if event["type"] == "error":
                    raise RuntimeError(event["payload"]["message"])
                chunk_count += 1
                
            logger.info(f"Sent {chunk_count} chunks. Sending end_of_input control event.")
            await ws.send(json.dumps({"type": "end_of_input", "payload": {}}))
            while True:
                event = json.loads(await ws.recv())
                logger.info(f"Stream event: {event}")
                if event["type"] == "completed":
                    break
                if event["type"] == "error":
                    raise RuntimeError(event["payload"]["message"])
            
            # Allow time for buffer queue to flush out to sound card
            await asyncio.sleep(2.5)
            logger.info("Playback test completed successfully.")
            
    except Exception as e:
        logger.error(f"E2E Test error occurred: {e}")
    finally:
        logger.info("Shutting down background server process...")
        server_process.terminate()
        try:
            server_process.wait(timeout=2.0)
            logger.info("Server terminated gracefully.")
        except subprocess.TimeoutExpired:
            logger.warning("Force terminating server process.")
            server_process.kill()

if __name__ == "__main__":
    asyncio.run(run_test())
