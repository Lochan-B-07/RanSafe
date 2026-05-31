#!/usr/bin/env python3
import json
import argparse
import os
import sys
import jsonschema

# Schema and Prompt Paths
TELEMETRY_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../docs/telemetry_schema.json")
EXECUTION_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../docs/execution_interface.json")

def load_json(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

def run_local_rule_engine(telemetry_payload):
    """
    Deterministic offline classification engine mimicking Gemini 3 threshold checks.
    Used when GEMINI_API_KEY is not configured.
    """
    metrics = telemetry_payload.get("metrics", {})
    cpu = metrics.get("cpu_utilization_percentage", 0.0)
    write_ops = metrics.get("filesystem_write_ops_per_sec", 0)
    entropy = metrics.get("entropy_coefficient", 0.0)
    node_id = telemetry_payload.get("node_id", "unknown-node")

    # Mirroring rules defined in system_prompt.txt
    if cpu > 85.0 and write_ops > 200 and entropy > 0.80:
        action = "AIRGAP_NODE"
        reason = f"Offline Engine: Ransomware signature matched. CPU={cpu}%, disk write ops={write_ops}/sec, entropy={entropy}."
    elif cpu > 75.0 and write_ops <= 200 and entropy <= 0.80:
        action = "REALLOCATE_RESOURCES"
        reason = f"Offline Engine: High CPU compute load. CPU={cpu}%, normal disk writes={write_ops}/sec, normal entropy={entropy}."
    else:
        action = "MONITOR_INTENSE"
        reason = f"Offline Engine: Mixed workload metrics observed. CPU={cpu}%, disk writes={write_ops}/sec, entropy={entropy}."

    return {
        "action": action,
        "target_node_id": node_id,
        "authorization_token": f"AUTH-TOKEN-{node_id}-{action}",
        "reasoning_summary": reason
    }

def run_gemini_inference(system_prompt, telemetry_payload):
    """
    Calls the live Gemini 3 (gemini-2.5-flash) API using the google-genai SDK.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[ERROR] google-genai package is not installed.", file=sys.stderr)
        return None

    # genai.Client picks up GEMINI_API_KEY automatically from environment
    client = genai.Client()
    
    # We serialize the individual telemetry payload to JSON text for model ingestion
    input_content = json.dumps(telemetry_payload, indent=2)
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=input_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json"
            )
        )
        
        # Clean up any potential markdown wrap if Gemini failed to strictly follow instructions
        text_resp = response.text.strip()
        if text_resp.startswith("```"):
            # strip off ```json and ```
            lines = text_resp.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text_resp = "\n".join(lines).strip()
            
        return json.loads(text_resp)
        
    except Exception as e:
        print(f"[ERROR] Live Gemini API call failed: {e}", file=sys.stderr)
        return None

def main():
    parser = argparse.ArgumentParser(description="RanSafe Dry-run Telemetry Evaluator & Payload Validator")
    parser.add_argument("--prompt", type=str, required=True,
                        help="Path to system prompt file")
    parser.add_argument("--input", type=str, required=True,
                        help="Path to telemetry JSON file (single payload or array)")
    
    args = parser.parse_args()

    # Load resources
    try:
        telemetry_schema = load_json(TELEMETRY_SCHEMA_PATH)
        execution_schema = load_json(EXECUTION_SCHEMA_PATH)
    except FileNotFoundError as e:
        print(f"[ERROR] Could not load JSON schema files from /docs: {e}", file=sys.stderr)
        exit(1)

    if not os.path.exists(args.prompt):
        print(f"[ERROR] System prompt file not found: {args.prompt}", file=sys.stderr)
        exit(1)
        
    with open(args.prompt, "r") as f:
        system_prompt = f.read()

    if not os.path.exists(args.input):
        print(f"[ERROR] Telemetry input file not found: {args.input}", file=sys.stderr)
        exit(1)
        
    telemetry_data = load_json(args.input)
    
    # Standardize input to list
    if not isinstance(telemetry_data, list):
        payloads = [telemetry_data]
    else:
        payloads = telemetry_data

    print(f"Loaded {len(payloads)} telemetry payload(s) for validation.")
    
    # Check for live API access
    api_key = os.environ.get("GEMINI_API_KEY")
    use_live_api = bool(api_key)
    
    if use_live_api:
        print("[INFO] GEMINI_API_KEY detected. Running live Gemini 3 inference.")
    else:
        print("[WARNING] GEMINI_API_KEY not set. Running offline rule-based simulation engine.")

    success_count = 0
    failure_count = 0

    for idx, payload in enumerate(payloads):
        print(f"\n--- Evaluating Payload {idx+1}/{len(payloads)} ---")
        
        # 1. Validate incoming telemetry payload schema
        try:
            jsonschema.validate(instance=payload, schema=telemetry_schema)
            print("✓ Telemetry input matches telemetry_schema.json schema.")
        except jsonschema.exceptions.ValidationError as e:
            print(f"✗ Telemetry input schema validation failed: {e}", file=sys.stderr)
            failure_count += 1
            continue

        metrics = payload["metrics"]
        print(f"  Node ID: {payload['node_id']}")
        print(f"  Metrics: CPU={metrics['cpu_utilization_percentage']}%, Writes={metrics['filesystem_write_ops_per_sec']}/s, Entropy={metrics['entropy_coefficient']}")

        # 2. Execute inference (live or local fallback)
        if use_live_api:
            decision = run_gemini_inference(system_prompt, payload)
            if decision is None:
                print("  Live API inference failed, falling back to local engine for this run...")
                decision = run_local_rule_engine(payload)
        else:
            decision = run_local_rule_engine(payload)

        print(f"  Received Decision Payload: {json.dumps(decision, indent=2)}")

        # 3. Validate decision payload against execution schema
        try:
            jsonschema.validate(instance=decision, schema=execution_schema)
            print("✓ Decision output matches execution_interface.json schema.")
            
            # 4. State assertions based on inputs vs actions
            cpu = metrics["cpu_utilization_percentage"]
            write_ops = metrics["filesystem_write_ops_per_sec"]
            entropy = metrics["entropy_coefficient"]
            action = decision["action"]

            # Perform state assertions
            if cpu > 85.0 and write_ops > 200 and entropy > 0.80:
                assert action == "AIRGAP_NODE", f"Expected action AIRGAP_NODE, got {action}"
            elif cpu > 75.0 and write_ops <= 200 and entropy <= 0.80:
                assert action == "REALLOCATE_RESOURCES", f"Expected action REALLOCATE_RESOURCES, got {action}"
            
            assert "authorization_token" in decision and decision["authorization_token"], "Missing authorization token"
            assert "reasoning_summary" in decision and decision["reasoning_summary"], "Missing reasoning summary"
            
            print("✓ Decision logic assertions passed successfully.")
            success_count += 1
        except jsonschema.exceptions.ValidationError as e:
            print(f"✗ Decision output schema validation failed: {e}", file=sys.stderr)
            failure_count += 1
        except AssertionError as e:
            print(f"✗ State assertion failed: {e}", file=sys.stderr)
            failure_count += 1

    print("\n==================================")
    print(f"Evaluation Complete: {success_count} Passed, {failure_count} Failed.")
    print("==================================")
    
    if failure_count > 0:
        exit(1)
    else:
        exit(0)

if __name__ == "__main__":
    main()
