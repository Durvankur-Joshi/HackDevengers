import sys
import os
import json

# Ensure backend root is first in sys.path and remove current directory to avoid module shadowing
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, "../.."))
if current_dir in sys.path:
    sys.path.remove(current_dir)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.services.supabase import supabase_service


def run_verification():
    print("=== Document-to-Action Pipeline: Supabase Verification ===")
    
    if not supabase_service.is_configured():
        print("[-] Supabase is NOT configured.")
        print("[-] Please provide SUPABASE_URL and SUPABASE_KEY in backend/.env to connect.")
        return False

    print("[+] Supabase configuration detected.")
    print("[*] Testing database connectivity (GET /health/db equivalent)...")
    health = supabase_service.check_connection()
    print(f"[*] Connection status: {json.dumps(health, indent=2)}")

    if health.get("database") != "connected":
        print("[-] Database connection failed. Please verify that docs/database.sql was executed in Supabase SQL editor.")
        return False

    print("[+] Database connected successfully!")
    print("[*] Performing test document round-trip (Insert -> Retrieve -> Delete)...")
    result = supabase_service.verify_roundtrip()
    print(f"[*] Lifecycle result: {json.dumps(result, indent=2)}")

    if result.get("success"):
        print("[+] Test document successfully inserted, verified, and cleaned up!")
        return True
    else:
        print(f"[-] Lifecycle test failed: {result.get('error')}")
        return False


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
