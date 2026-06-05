"""
End-to-end integration test for the STT Microservice HTTP API.

Prerequisites:
    - The server must be running at http://127.0.0.1:8001
      (launch via VS Code or `python main.py`)
"""

import httpx
import asyncio
import time

BASE_URL = "http://127.0.0.1:8001"


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def print_header(title: str) -> None:
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print(f"{'─'*50}")


def print_result(label: str, success: bool, detail: str = "") -> None:
    icon = "✅" if success else "❌"
    msg = f"  {icon} {label}"
    if detail:
        msg += f"  →  {detail}"
    print(msg)


# ──────────────────────────────────────────────
# TEST STEPS
# ──────────────────────────────────────────────

async def test_health(client: httpx.AsyncClient) -> bool:
    print_header("1. Health Check  →  GET /health")
    try:
        resp = await client.get(f"{BASE_URL}/health")
        body = resp.json()
        ok = resp.status_code == 200 and body.get("status") == "success"
        print_result("Health", ok, f"status={resp.status_code}  body={body}")
        return ok
    except Exception as e:
        print_result("Health", False, f"Exception: {e}")
        return False


async def test_available(client: httpx.AsyncClient) -> bool:
    print_header("2. Availability Check  →  GET /available")
    try:
        resp = await client.get(f"{BASE_URL}/available")
        body = resp.json()
        ok = resp.status_code == 200 and body.get("data") is True
        print_result("Available", ok, f"status={resp.status_code}  body={body}")
        return ok
    except Exception as e:
        print_result("Available", False, f"Exception: {e}")
        return False


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

async def run_tests() -> None:
    print("\n" + "=" * 50)
    print("  STT Microservice  –  Integration Test")
    print("=" * 50)

    results: list[bool] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Health
        results.append(await test_health(client))

        # 2. Available
        results.append(await test_available(client))

    # Summary
    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 50)
    if passed == total:
        print(f"  ✅  ALL PASSED  ({passed}/{total})")
    else:
        print(f"  ❌  FAILURES  ({passed}/{total} passed)")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
