#!/usr/bin/env python3
import json
import argparse
import os
import sys
import jsonschema

# Try importing OpenTelemetry, failing gracefully if package is missing
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

# Initialize the Tracer dynamically
tracer = None
if HAS_OTEL:
    try:
        # Define resource name
        resource = Resource(attributes={"service.name": "ransafe-ai-validator"})
        provider = TracerProvider(resource=resource)
        
        # Load keys from environment (which can be populated via .env file)
        dt_url = os.environ.get("DYNATRACE_ENV_URL")
        dt_token = os.environ.get("DYNATRACE_API_TOKEN")
        
        if dt_url and dt_token:
            # Point to Dynatrace OTLP traces ingest v2 endpoint
            exporter = OTLPSpanExporter(
                endpoint=f"{dt_url.rstrip('/')}/api/v2/otlp/v1/traces",
                headers={"Authorization": f"Api-Token {dt_token}"}
            )
        else:
            exporter = ConsoleSpanExporter()
            
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("ransafe_tracer")
    except Exception as e:
        print(f"[WARNING] OTel initialization failed: {e}", file=sys.stderr)
        tracer = None

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
    Calls the live Gemini 3 (gemini-2.5-flash) API using the google-genai SDK,
    wrapping the model invocation in an active OpenTelemetry trace span.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[ERROR] google-genai package is not installed.", file=sys.stderr)
        return None

    client = genai.Client()
    input_content = json.dumps(telemetry_payload, indent=2)

    # Initialize trace span context if OTel is active
    span = None
    if tracer:
        try:
            span = tracer.start_span("gemini_threat_evaluation")
            span.set_attribute("genai.model", "gemini-2.5-flash")
            span.set_attribute("genai.prompt", input_content)
        except Exception:
            pass

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=input_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json"
            )
        )
        
        text_resp = response.text.strip()
        if text_resp.startswith("```"):
            lines = text_resp.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text_resp = "\n".join(lines).strip()

        # Successfully end span and set status
        if span:
            try:
                span.set_attribute("genai.response", text_resp)
                span.set_status(trace.Status(trace.StatusCode.OK))
                span.end()
            except Exception:
                pass
            
        return json.loads(text_resp)
        
    except Exception as e:
        # Record exceptions to the span before failing
        if span:
            try:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.end()
            except Exception:
                pass
        print(f"[ERROR] Live Gemini API call failed: {e}", file=sys.stderr)
        return None

def process_payload(payload, telemetry_schema, execution_schema, system_prompt, json_only):
    """
    Validates telemetry payload, runs Gemini inference, maps decisions,
    performs logic assertions, and returns the verified action payload.
    """
    # 1. Validate incoming telemetry payload schema
    try:
        jsonschema.validate(instance=payload, schema=telemetry_schema)
        if not json_only:
            print("✓ Telemetry input matches telemetry_schema.json schema.")
    except jsonschema.exceptions.ValidationError as e:
        print(f"✗ Telemetry input schema validation failed: {e}", file=sys.stderr)
        return None

    metrics = payload["metrics"]
    if not json_only:
        print(f"  Node ID: {payload['node_id']}")
        print(f"  Metrics: CPU={metrics['cpu_utilization_percentage']}%, Writes={metrics['filesystem_write_ops_per_sec']}/s, Entropy={metrics['entropy_coefficient']}")

    # Check for live API access
    api_key = os.environ.get("GEMINI_API_KEY")
    use_live_api = bool(api_key)

    # 2. Execute inference (live or local fallback)
    if use_live_api:
        decision = run_gemini_inference(system_prompt, payload)
        if decision is None:
            if not json_only:
                print("  Live API inference failed, falling back to local engine for this run...", file=sys.stderr)
            decision = run_local_rule_engine(payload)
    else:
        decision = run_local_rule_engine(payload)

    # Inject metrics and ensure node ID is present
    decision["metrics"] = metrics
    if "target_node_id" not in decision or not decision["target_node_id"]:
        decision["target_node_id"] = payload.get("node_id", "unknown-node")

    if not json_only:
        print(f"  Received Decision Payload: {json.dumps(decision, indent=2)}")

    # 3. Validate decision payload against execution schema
    try:
        jsonschema.validate(instance=decision, schema=execution_schema)
        if not json_only:
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
        
        if not json_only:
            print("✓ Decision logic assertions passed successfully.")
        
        return decision
    except jsonschema.exceptions.ValidationError as e:
        print(f"✗ Decision output schema validation failed: {e}", file=sys.stderr)
        return None
    except AssertionError as e:
        print(f"✗ State assertion failed: {e}", file=sys.stderr)
        return None

def main():
    parser = argparse.ArgumentParser(description="RanSafe Dry-run Telemetry Evaluator & Payload Validator")
    parser.add_argument("--prompt", type=str, required=True,
                        help="Path to system prompt file")
    parser.add_argument("--input", type=str, required=True,
                        help="Path to telemetry JSON file (single payload or array). Use '-' for stdin.")
    parser.add_argument("--json-only", action="store_true",
                        help="Output only the decision JSON to stdout; all log/debug messages go to stderr.")
    
    args = parser.parse_args()
    json_only = args.json_only

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

    success_count = 0
    failure_count = 0

    if args.input == "-":
        # Read from stdin line-by-line for continuous pipe support
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, list):
                    payloads = payload
                else:
                    payloads = [payload]
                
                for p in payloads:
                    decision = process_payload(p, telemetry_schema, execution_schema, system_prompt, json_only)
                    if decision:
                        success_count += 1
                        print(json.dumps(decision))
                        sys.stdout.flush()
                    else:
                        failure_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to parse/process stdin line: {e}", file=sys.stderr)
                failure_count += 1
    else:
        # File input mode
        if not os.path.exists(args.input):
            print(f"[ERROR] Telemetry input file not found: {args.input}", file=sys.stderr)
            exit(1)
        try:
            telemetry_data = load_json(args.input)
        except Exception as e:
            print(f"[ERROR] Failed to read/parse telemetry JSON file: {e}", file=sys.stderr)
            exit(1)

        if isinstance(telemetry_data, list):
            payloads = telemetry_data
        else:
            payloads = [telemetry_data]

        decisions = []
        for p in payloads:
            decision = process_payload(p, telemetry_schema, execution_schema, system_prompt, json_only)
            if decision:
                decisions.append(decision)
                success_count += 1
            else:
                failure_count += 1

        if json_only:
            if len(decisions) == 1:
                print(json.dumps(decisions[0]))
            else:
                print(json.dumps(decisions))
            sys.stdout.flush()
        else:
            print("\n==================================")
            print(f"Evaluation Complete: {success_count} Passed, {failure_count} Failed.")
            print("==================================")

    if failure_count > 0:
        exit(1)
    else:
        exit(0)

if __name__ == "__main__":
    main()
