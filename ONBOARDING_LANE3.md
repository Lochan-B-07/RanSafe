# Lane 3 Onboarding: AI Core & Orchestration

This document details the completed components in the `/agent` directory (Lane 3 Lead) and outlines how other lanes (Lanes 1, 2, and 4) hook into the AI reasoning core.

---

## 🚀 Overview of Lane 3 Work
We have successfully stood up the core validation and reasoning engine. This includes:
1. **Mock Metric Scenario Generator** (`agent/mock_generator.py`)
2. **Precision Reasoning Guidelines** (`agent/system_prompt.txt`)
3. **Threat Classification & Output Validator** (`agent/validator.py`)
4. **Dynatrace MCP Server Client** (`agent/mcp_client.js`)
5. **Automated Validation Test Suites** (`agent/test_agent.py` and `agent/test_mcp_client.js`)

---

## 🤝 Cross-Lane Integration Handshakes

### 1. For Lane 1 (Backend & Threat Simulation — `/sandbox`)
* **Your Goal**: Write the malware simulation script (`malware_sim.sh`) that triggers the circuit breaker.
* **Our Heuristics**: To trigger an immediate network containment (`AIRGAP_NODE`), your simulated ransomware loop must push system metrics past these exact thresholds simultaneously:
  - **CPU Utilization**: `> 85%`
  - **Filesystem Write Ops/Sec**: `> 200`
  - **Entropy Coefficient**: `> 0.80` (representing file-write encryption patterns)
* **Prototyping**: You can use `python3 agent/mock_generator.py --mode ransomware` to generate mock data matching your attack signature and verify it outputs correctly.

### 2. For Lane 2 (Cloud Ops & System Management — `/observability`)
* **Your Goal**: Run the Dynatrace MCP Server.
* **Our Connection**: The client script `agent/mcp_client.js` queries your server using JSON-RPC requests over standard I/O (or SSE). It queries the resource:
  `dynatrace://nodes/{nodeId}/metrics`
* **Data Contract**: Your MCP server must output telemetry that strictly matches the schema in `docs/telemetry_schema.json`. 
* **Error Handling**: `agent/mcp_client.js` enforces strict type checking (e.g., verifying `filesystem_write_ops_per_sec` is an integer, and `cpu_utilization` is a float). If your server emits mismatched schemas, the client will immediately throw an assertion exception to prevent bad data state propagation.
* **Sandbox Ingestion Endpoint**: When running `agent/mcp_client.js` in mock/sandbox mode (`--mock` or when `--server-path` is omitted), the client queries the live container sandbox HTTP endpoint directly: `https://ransafe-sandbox-453397284615.us-central1.run.app` to fetch active streaming metrics from the sandbox.

### 3. For Lane 4 (Infrastructure Execution & UX — `/execution`)
* **Your Goal**: Capture the containment action and isolate the network interface.
* **Our Output**: The reasoning core (`agent/validator.py`) outputs structured JSON payloads conforming to `docs/execution_interface.json`.
* **Decision Types**:
  - `AIRGAP_NODE`: Severe ransomware signature matched. Trigger immediate network containment.
  - `REALLOCATE_RESOURCES`: High CPU load with normal entropy/disk writes. Scale resources without airgapping.
  - `MONITOR_INTENSE`: Elevated/suspicious metrics. Increase logging cadence.
* **Command Binding**: You can pipe our validator outputs directly into your execution router.

---

## 🛠️ Running Tools & Test Suites

Ensure you have `jsonschema` installed:
```bash
pip install jsonschema
```

### Run Automated Unit Tests
Verify that all metrics generation, schema validations, and threshold rules pass:
```bash
# Run Python Unit Tests
python3 -m unittest agent/test_agent.py

# Run Node.js Unit Tests
node agent/test_mcp_client.js
```

### Generate Mock Datasets
Generate scenario metrics representing normal compute baseline or ransomware activity:
```bash
# Normal Scenario
python3 agent/mock_generator.py --mode normal --count 5 --output agent/mock_normal.json

# Ransomware Threat Scenario
python3 agent/mock_generator.py --mode ransomware --count 5 --output agent/mock_ransomware.json
```

### Run Dry-Run Threat Evaluation
Run the decision pipeline locally to verify how Gemini 3 / local fallback rule engine classifies the metrics:
```bash
# Evaluates normal telemetry -> results in MONITOR_INTENSE or REALLOCATE_RESOURCES
python3 agent/validator.py --prompt agent/system_prompt.txt --input agent/mock_normal.json

# Evaluates ransomware telemetry -> results in AIRGAP_NODE
python3 agent/validator.py --prompt agent/system_prompt.txt --input agent/mock_ransomware.json
```

*Note: If `GEMINI_API_KEY` is not present in your environment, the validator automatically runs a rule-based simulation engine to allow offline testing.*
