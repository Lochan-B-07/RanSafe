# RanSafe Lane 4 (Member 4) Detailed Progress Report
**Role: Infrastructure Execution & UX Lead (Krishna)**

This report details the engineering work, code implementation, and integration handshakes completed for **Lane 4 (Infrastructure Execution & UX)**. The objective of this lane is to ingest the AI agent's JSON mitigation decisions, translate them into state-mutating cloud API actions to sever compromised nodes, and build a high-fidelity visual dashboard to showcase the automated containment process for the hackathon demo.

---

## 🛠️ Complete Technical Breakdown of Deliverables

### 1. Unified Control Daemon & Validation Gateway (`handler.py`)
The `handler.py` script acts as the entrypoint for the execution pipeline, listening to a stream of decisions piped from the AI agent.

* **Payload Validation Gateway:**
  * Imports the `jsonschema` library to perform validation on incoming streams.
  * Resolves and reads the schema from `docs/execution_interface.json`.
  * Verifies that all required fields (`action`, `target_node_id`, `authorization_token`, `reasoning_summary`) are present and conform to types (e.g., verifying `action` is one of the enum values: `AIRGAP_NODE`, `REALLOCATE_RESOURCES`, or `MONITOR_INTENSE`).
  * If a payload is malformed or missing fields, the daemon logs the validation error inside the visual console window and gracefully continues listening without executing mutations.
* **Premium Cybersecurity Console UI:**
  * Uses standard ANSI escape codes for coloring, styling, and console formatting (no external dependencies required, ensuring compatibility).
  * Clears the terminal screen on updates to render a static, flickering-free status grid.
  * Displays a custom ANSI-colored RanSafe ASCII banner, status cards for node integrity, and circuit switch state blocks:
    * **Nominal / Listening:** Green indicator (`🟢 CLOSED - STEADY NOMINAL STATE`).
    * **Monitor Intense:** Yellow warning (`⚠️ WARN - HIGH FREQUENCY OBSERVABILITY`).
    * **Resource Scaling:** Yellow notice (`🟢 CLOSED - ACTIVE RESOURCE AUTOMATION`).
    * **Airgap Active:** Blinking red critical alarm (`🚨 OPENED - CRITICAL ANOMALY AIRGAP ACTIVE`).
* **Execution Log Piping:**
  * Captures `stdout` and `stderr` streams of the executed bash scripts in real-time.
  * Parses lines and auto-formats them based on output keywords (e.g., lines containing "Success" or "✅" are colored green, "Error" or "❌" are colored red, and warnings are colored yellow).
  * Aggregates them into a rotating queue displayed in the UI's live logging window.

---

### 2. State-Mutating Rules Engine (`airgap_rules.sh`)
This bash script executes the state changes on the cloud provider. It is called by `handler.py` and receives `TARGET_NODE`, `ACTION_TOKEN`, `AUTH_TOKEN`, and `AI_REASONING` as parameters.

* **GCP Secret Manager Authentication:**
  * Contains the command structure to query Google Cloud Secret Manager for security credentials:
    ```bash
    gcloud secrets versions access latest --secret="ransafe-auth-key"
    ```
* **5-Step Cloud Containment Sequence (`AIRGAP_NODE`):**
  1. **Cloud Armor Security Rule Mutation:** Dynamically edits security policies to drop incoming traffic targeting the compromised node:
     ```bash
     gcloud compute security-policies rules create 1000 --security-policy="ransafe-armor-policy" --src-ip-ranges="*" --action="deny(403)"
     ```
  2. **VPC Firewall Block:** Deploys an emergency VPC firewall rule targeting the compromised tag:
     ```bash
     gcloud compute firewall-rules create "ransafe-airgap-$TARGET_NODE" --direction=INGRESS --priority=1000 --action=DENY --rules=all --target-tags="$TARGET_NODE"
     ```
  3. **IAM Privilege Revocation:** Revokes the `roles/editor` role from the instance's associated Google Cloud Service Account to halt lateral movement:
     ```bash
     gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$COMPROMISED_SA" --role="roles/editor"
     ```
  4. **GKE Container Pod Eviction:** Force-kills the GKE container pod running in the cluster namespace:
     ```bash
     kubectl delete pod "$TARGET_NODE" --namespace="production" --force --grace-period=0
     ```
  5. **Clean Backup Replicator:** Triggers a deployment rollout to spin up a clean replica node:
     ```bash
     kubectl rollout restart deployment/app-replica-deployment --namespace="production"
     ```
* **High-Fidelity Dry-Run Fallback:**
  * Checks if `gcloud` is logged into an active account. If no active session is found, it automatically switches to a dry-run mode.
  * In dry-run mode, it outputs simulated GCP API commands and successful validation states so the UI dashboard can display the mitigation pipeline locally for the judges.

---

### 3. Cloud Reversion & Cleanup Handler (`restore_network.sh`)
A utility script used to reverse containment actions once a threat is cleared.

* **Cloud Armor Rule Deletion:** Deletes the emergency block rules from the security policy.
* **VPC Firewall Deletion:** Removes the emergency VPC deny rules.
* **IAM Binding Restoration:** Re-associates the `roles/editor` binding to the service account.
* **GKE Health Check:** Inspects pod statuses in the namespace to confirm the cluster has returned to a nominal state.

---

## 🧪 Verification Commands

To verify and run the Lane 4 components, execute the following commands in the terminal:

### A. Run Elevated Monitoring Warning
```bash
echo '{"action": "MONITOR_INTENSE", "target_node_id": "k8s-pod-node-xyz", "authorization_token": "token123", "reasoning_summary": "Suspicious CPU activity"}' | python3 execution/handler.py
```

### B. Run Airgap Containment (Halt Checkpoint)
```bash
echo '{"action": "AIRGAP_NODE", "target_node_id": "k8s-pod-node-xyz", "authorization_token": "token123", "reasoning_summary": "Ransomware encryption activity matched rules"}' | python3 execution/handler.py
```

### C. Revert and Restore Infrastructure
```bash
./execution/restore_network.sh "k8s-pod-node-xyz"
```
