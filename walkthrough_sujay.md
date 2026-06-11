# Walkthrough: RanSafe AI Core Setup & Prompt Calibration

This document outlines the updates made to the RanSafe AI Core (Lane 3) for the hackathon. These changes initialize the Google Cloud Agent Builder workspace context, calibrate the Gemini 3 system prompt rules, and add automated mock unit tests to verify the pipeline.

---

## 🛠️ Summary of Deliverables

### 1. Agent Builder Workspace Setup
To define the workspace context inside Google Cloud Agent Builder console, we created:
* **[agent_builder_config.json](file:///home/suzaykid/Projects/RanSafe/agent/agent_builder_config.json)**: Specifies the Agent Builder workspace settings, selecting `gemini-2.5-flash` at `0.0` temperature to ensure deterministic outputs, referencing instructions and schemas.
* **[agent_tools_openapi.json](file:///home/suzaykid/Projects/RanSafe/docs/agent_tools_openapi.json)**: OpenAPI 3.0 tool definitions registering the following tools in Agent Builder:
  - `get_telemetry_metrics` (for fetching Dynatrace node metrics).
  - `execute_mitigation_action` (for triggering node containment/reallocation).

### 2. Gemini 3 System Prompt Calibration
The system prompt **[system_prompt.txt](file:///home/suzaykid/Projects/RanSafe/agent/system_prompt.txt)** was calibrated to ensure Gemini 3 reliably returns the exact JSON format defined in `docs/execution_interface.json`.
* **Threshold rules** are reinforced:
  - `AIRGAP_NODE` if CPU > 85.0%, Disk Writes > 200/s, and Entropy Coeff > 0.80.
  - `REALLOCATE_RESOURCES` if CPU > 75.0%, Disk Writes <= 200/s, and Entropy Coeff <= 0.80.
  - `MONITOR_INTENSE` for all other elevated/mixed workloads.
* **Formatting instructions** explicitly prohibit conversational text and markdown formatting wrappers (like ` ```json ` blocks).
* **One-shot examples** are injected for each decision scenario to guide the model towards perfect formatting and token string formats (e.g. `AUTH-TOKEN-<target_node_id>-<action>`).

### 3. Mock Unit Tests & Verification
We added mock unit tests in **[test_agent.py](file:///home/suzaykid/Projects/RanSafe/agent/test_agent.py)** to test the live model interface without performing live remote API calls:
* `test_run_gemini_inference_success`: Verifies correct data ingestion and execution schema validation.
* `test_run_gemini_inference_markdown_cleanup`: Verifies that if Gemini returns JSON wrapped in markdown ` ```json ` tags, the code successfully cleans it up and parses the JSON.
* `test_run_gemini_inference_failure`: Verifies error handling and graceful fallbacks when the live API call fails.

### 4. Live Container Sandbox Data Ingestion Hook
We updated the `agent/mcp_client.js` data ingestion hook:
* **Target Ingestion Source**: Changed from the local mock telemetry payload generator to point directly to the live container sandbox HTTP endpoint: `https://ransafe-sandbox-453397284615.us-central1.run.app`.
* **Behavior**: When running the orchestrator or `mcp_client.js` in mock mode (`--mock`), the client performs a live asynchronous HTTP fetch to retrieve streaming metrics from the sandbox, validates the telemetry payload against `docs/telemetry_schema.json`, and feeds it into the validator.
* **Validation**: Verified that the live telemetry payload is correctly formatted and parsed by the rule engine and Gemini.

---

## 🧪 Verification Commands

You can verify that all configurations and prompt parser validations are correct by running the test suites:

```bash
# Run Python Unit Tests (includes local rule engine and mocked live Gemini tests)
python3 -m unittest agent/test_agent.py

# Run Node.js Unit Tests (verifies telemetry schema mappings)
node agent/test_mcp_client.js

# Test live telemetry retrieval from the Cloud Run sandbox endpoint
node agent/mcp_client.js --mock

# Run end-to-end pipeline ingestion test from the sandbox through the validator
node agent/mcp_client.js --mock --json-only | python3 agent/validator.py --prompt agent/system_prompt.txt --input -
```
All tests should pass successfully.
