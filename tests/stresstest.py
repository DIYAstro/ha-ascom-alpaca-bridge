import asyncio
import aiohttp
import os
import sys
import time
import argparse
import math
from typing import List, Dict, Any
from datetime import datetime
from pathlib import Path

def load_secrets():
    """Load secrets from deployconf.secrets or .secrets files if they exist."""
    secrets = {}
    # Check current dir and project root for both naming conventions
    paths = [
        Path("deployconf.secrets"), Path("../deployconf.secrets"), Path("../../deployconf.secrets"),
        Path(".secrets"), Path("../.secrets"), Path("../../.secrets")
    ]
    for p in paths:
        if p.exists():
            with open(p, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        secrets[k.strip()] = v.strip()
            # If we found a file, we stop looking. Priority to the first one found in the path list.
            break
    return secrets

SECRETS = load_secrets()

# --- Configuration & Defaults ---
DEFAULT_HA_URL = SECRETS.get("HA_URL", "http://localhost:8123")
DEFAULT_HA_TOKEN = SECRETS.get("HA_TOKEN", "")

class AlpacaHAStressTester:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "content-type": "application/json",
        }
        self.entities = []

    async def check_connection(self):
        """Verify we can talk to HA."""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(f"{self.url}/api/config", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        config = await resp.json()
                        return True, config.get("version", "Unknown")
                    return False, f"HTTP {resp.status}"
            except Exception as e:
                return False, str(e)

    async def discover_entities(self):
        """Find all Alpaca Bridge entities."""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            # 1. Get exact entity IDs belonging to our integration via HA Template API
            template_payload = {"template": "{{ integration_entities('ascom_alpaca_bridge') }}"}
            integration_entity_ids = []
            try:
                async with session.post(f"{self.url}/api/template", json=template_payload, timeout=aiohttp.ClientTimeout(total=10)) as t_resp:
                    if t_resp.status == 200:
                        import ast
                        text = await t_resp.text()
                        integration_entity_ids = ast.literal_eval(text)
            except Exception:
                pass
                
            # 2. Get all current states
            try:
                async with session.get(f"{self.url}/api/states", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    states = await resp.json()
            except Exception:
                return []
                
            if integration_entity_ids:
                self.entities = [s for s in states if s["entity_id"] in integration_entity_ids]
            else:
                # Fallback
                self.entities = [
                    s for s in states 
                    if "alpaca" in s["entity_id"].lower() 
                    or "alpaca" in s.get("attributes", {}).get("friendly_name", "").lower()
                ]
            return self.entities

    def print_table(self, entities):
        """Print status table."""
        print(f"\n{'Entity ID':<60} | {'State':<15} | {'Last Changed'}")
        print("-" * 110)
        for e in sorted(entities, key=lambda x: x["entity_id"]):
            eid = e["entity_id"]
            st = e["state"]
            lc = e.get("last_changed", "N/A")
            # Format time for readability
            try:
                dt = datetime.fromisoformat(lc.replace("Z", "+00:00"))
                lc_str = dt.strftime("%H:%M:%S")
            except:
                lc_str = lc
            
            symbol = "✓" if st not in ["unavailable", "unknown"] else "✗"
            print(f"{eid:<60} | {st:<15} | {symbol} {lc_str}")

    async def run_audit(self):
        """Simple audit of all entities."""
        print(f"\n[Audit] Discovering entities at {self.url}...")
        entities = await self.discover_entities()
        if not entities:
            print("No entities found.")
            return
        
        self.print_table(entities)
        online = sum(1 for e in entities if e["state"] not in ["unavailable", "unknown"])
        print(f"\nTotal: {len(entities)} | Online: {online} | Offline: {len(entities) - online}")

    async def run_monitor(self, interval=2):
        """Live monitor for state changes."""
        print(f"\n[Monitor] Watching for changes every {interval}s. Press Ctrl+C to stop.")
        
        last_states = {}
        entities = await self.discover_entities()
        for e in entities:
            last_states[e["entity_id"]] = e["state"]

        try:
            while True:
                await asyncio.sleep(interval)
                current_entities = await self.discover_entities()
                changes = []
                for e in current_entities:
                    eid = e["entity_id"]
                    new_st = e["state"]
                    old_st = last_states.get(eid)
                    if old_st and new_st != old_st:
                        changes.append((eid, old_st, new_st))
                        last_states[eid] = new_st

                if changes:
                    ts = datetime.now().strftime("%H:%M:%S")
                    for eid, old, new in changes:
                        print(f"[{ts}] {eid}: {old} -> {new}")
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")

    async def call_service(self, domain, service, entity_id, data=None):
        """Trigger a service call in HA."""
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)
            
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.post(f"{self.url}/api/services/{domain}/{service}", json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    return resp.status == 200
        except Exception as e:
            print(f" Service call exception: {e} ", end="")
            return False

    async def run_stress_test(self):
        """Actively toggle inputs to test loopback latency."""
        entities = await self.discover_entities()
        
        testable = [e for e in entities if e["entity_id"].startswith(("switch.", "number.", "select."))]
        if not testable:
            print("Error: No testable Alpaca inputs found.")
            return
            
        print(f"\n[Stress] Found {len(testable)} inputs for testing.")
        
        for ent in testable:
            target = ent["entity_id"]
            print(f"\n--- Testing loopback on {target} ---")
            
            # Fetch fresh
            active_ents = await self.discover_entities()
            target_ent = next((e for e in active_ents if e["entity_id"] == target), None)
            if not target_ent or target_ent["state"] in ["unavailable", "unknown"]:
                print(f"Entity {target} unavailable. Skipping.")
                continue

            domain = target.split(".")[0]
            start_state = target_ent["state"]
            attrs = target_ent.get("attributes", {})
            
            # Determine alternating values
            val1 = None
            val2 = None
            service = ""
            payload_key = ""
            
            if domain == "switch":
                val1 = "on" if start_state == "off" else "off"
                val2 = start_state
            elif domain == "number":
                service = "set_value"
                payload_key = "value"
                try:
                    curr = float(start_state)
                    step = float(attrs.get("step", 1.0))
                    c_max = float(attrs.get("max", curr + step))
                    c_min = float(attrs.get("min", curr - step))
                    
                    if curr + step <= c_max:
                        val1 = curr + step
                    else:
                        val1 = curr - step
                    val2 = curr
                    
                    # Ensure format
                    if step.is_integer() and curr.is_integer():
                        val1 = int(val1)
                        val2 = int(val2)
                except Exception as e:
                    print(f"Could not parse numeric state {start_state}. Skipping.")
                    continue
            elif domain == "select":
                service = "select_option"
                payload_key = "option"
                options = attrs.get("options", [])
                if len(options) < 2:
                    print("Not enough options to toggle. Skipping.")
                    continue
                # Pick an option that is not current
                other_opt = next((o for o in options if o != start_state), options[0])
                val1 = other_opt
                val2 = start_state

            if val1 is None:
                continue
                
            print("This will toggle the value 3 times and measure state reflection time.")
            
            for i in range(3):
                target_val = val1 if i % 2 == 0 else val2
                expected = str(target_val).lower() if domain != "select" else str(target_val)
                
                action_service = service
                if domain == "switch":
                    action_service = "turn_on" if target_val == "on" else "turn_off"
                    payload = {}
                else:
                    payload = {payload_key: target_val}

                print(f"Cycle {i+1}: Changing to {target_val}... ", end="", flush=True)
                start_time = time.time()
                if await self.call_service(domain, action_service, target, payload):
                    # Poll until state changes
                    while True:
                        await asyncio.sleep(0.3)
                        poll_ents = await self.discover_entities()
                        p_ent = next((e for e in poll_ents if e["entity_id"] == target), None)
                        if p_ent:
                            p_state = p_ent["state"]
                            match = False
                            if domain == "switch" and p_state == expected:
                                match = True
                            elif domain == "select" and p_state == expected:
                                match = True
                            elif domain == "number":
                                try:
                                    if math.isclose(float(p_state), float(expected), rel_tol=1e-5, abs_tol=1e-5):
                                        match = True
                                except:
                                    pass
                                    
                            if match:
                                elapsed = time.time() - start_time
                                print(f"DONE (Reflected in {elapsed:.2f}s)")
                                break
                                
                        if time.time() - start_time > 10:
                            print("TIMEOUT (State did not change after 10s)")
                            break
                else:
                    print("FAILED to call service.")
                
                await asyncio.sleep(1.5)

async def main():
    parser = argparse.ArgumentParser(description="Alpaca HA Stress Test Tool")
    parser.add_argument("--url", default=os.environ.get("HA_URL", DEFAULT_HA_URL), help="HA Base URL")
    parser.add_argument("--token", default=os.environ.get("HA_TOKEN", DEFAULT_HA_TOKEN), help="HA Access Token")
    parser.add_argument("--mode", choices=["audit", "monitor", "stress"], default="audit", help="Operation mode")
    parser.add_argument("--interval", type=int, default=2, help="Polling interval for monitor")
    
    args = parser.parse_args()
    
    tester = AlpacaHAStressTester(args.url, args.token)
    
    success, version = await tester.check_connection()
    if not success:
        print(f"❌ Connection failed: {version}")
        sys.exit(1)
        
    print(f"✅ Connected to Home Assistant {version}")
    
    if args.mode == "audit":
        await tester.run_audit()
    elif args.mode == "monitor":
        await tester.run_monitor(args.interval)
    elif args.mode == "stress":
        await tester.run_stress_test()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
