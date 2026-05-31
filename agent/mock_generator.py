#!/usr/bin/env python3
import json
import argparse
import random
import os
from datetime import datetime, timezone
import jsonschema

# Load telemetry schema for validation
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../docs/telemetry_schema.json")

def load_schema():
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

def generate_metrics(mode):
    if mode == "normal":
        # Low, normal baseline performance
        cpu = round(random.uniform(5.0, 45.0), 2)
        write_ops = random.randint(5, 30)
        entropy = round(random.uniform(0.1, 0.4), 3)
    elif mode == "ransomware":
        # Massive CPU spikes, intense I/O writes, and high entropy (encryption)
        cpu = round(random.uniform(85.0, 99.9), 2)
        write_ops = random.randint(200, 800)
        entropy = round(random.uniform(0.8, 1.0), 3)
    else: # mixed
        # Intermittent behavior, randomly normal or suspicious
        if random.random() < 0.3:
            cpu = round(random.uniform(70.0, 95.0), 2)
            write_ops = random.randint(100, 300)
            entropy = round(random.uniform(0.5, 0.85), 3)
        else:
            cpu = round(random.uniform(10.0, 50.0), 2)
            write_ops = random.randint(10, 50)
            entropy = round(random.uniform(0.1, 0.45), 3)
            
    return {
        "cpu_utilization_percentage": cpu,
        "filesystem_write_ops_per_sec": write_ops,
        "entropy_coefficient": entropy
    }

def main():
    parser = argparse.ArgumentParser(description="RanSafe Telemetry Mock Stream Generator")
    parser.add_argument("--mode", choices=["normal", "ransomware", "mixed"], default="normal",
                        help="Telemetry scenario (normal workload, ransomware activity, or mixed behavior)")
    parser.add_argument("--count", type=int, default=5,
                        help="Number of data points to generate (keep under 100 to avoid CPU/RAM overhead)")
    parser.add_argument("--node-id", type=str, default="node-us-east-412",
                        help="Mock target compute node ID")
    parser.add_argument("--output", type=str,
                        help="Path to write output file (JSON array). Prints to stdout if not provided")
    
    args = parser.parse_args()
    
    if args.count <= 0 or args.count > 100:
        print("Error: Keep count between 1 and 100 to protect local MacBook resource pool.")
        exit(1)
        
    schema = load_schema()
    payloads = []
    
    # Generate timestamp starting now, descending backward or forward
    base_time = datetime.now(timezone.utc)
    
    for i in range(args.count):
        # Stagger timestamp back by 10s increments
        timestamp_str = base_time.isoformat().replace("+00:00", "Z")
        metrics = generate_metrics(args.mode)
        
        payload = {
            "node_id": args.node_id,
            "metrics": metrics,
            "timestamp": timestamp_str
        }
        
        # Verify schema
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            print(f"Internal Error: Generated payload fails schema validation! {e}")
            exit(1)
            
        payloads.append(payload)
    
    # Output results
    output_json = json.dumps(payloads, indent=2)
    if args.output:
        # Ensure directories exist
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Successfully generated {args.count} records ({args.mode} mode) in: {args.output}")
    else:
        print(output_json)

if __name__ == "__main__":
    main()
