#!/usr/bin/env bash

# RanSafe SRE Orchestrator - End-to-End Pipeline Coordinator
# Continuous piping: Dynatrace MCP Client -> AI Validator -> Execution Gateway.

set -euo pipefail

# Default parameters
MODE="ransomware"
NODE_ID="node-us-east-412"
LOOP=false

# Usage help
show_help() {
    echo "Usage: ./run_orchestrator.sh [options]"
    echo "Options:"
    echo "  --mode <normal|reallocate|ransomware>   Telemetry scenario mode (Default: ransomware)"
    echo "  --node-id <id>                          Target compute node ID (Default: node-us-east-412)"
    echo "  --loop, -l                              Run continuously in a loop (Default: false)"
    echo "  -h, --help                              Show this help menu"
    exit 0
}

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --node-id)
            NODE_ID="$2"
            shift 2
            ;;
        --loop|-l)
            LOOP=true
            shift 1
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load local .env file if present
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "[INFO] Loading local environment variables from .env"
    export $(grep -v '^#' "${SCRIPT_DIR}/.env" | xargs)
fi

# Run pipeline execution
echo "=========================================================="
echo "🛡️  RanSafe Continuous Pipeline Orchestration Starting..."
echo "Mode: ${MODE}"
echo "Node ID: ${NODE_ID}"
echo "Loop: ${LOOP}"
echo "=========================================================="

if [ "$LOOP" = true ]; then
    (
        while true; do
            node "${SCRIPT_DIR}/agent/mcp_client.js" --mock --mode="${MODE}" --node-id="${NODE_ID}" --json-only
            sleep 5
        done
    ) | \
    python3 "${SCRIPT_DIR}/agent/validator.py" --prompt "${SCRIPT_DIR}/agent/system_prompt.txt" --input - --json-only | \
    python3 "${SCRIPT_DIR}/execution/handler.py"
else
    node "${SCRIPT_DIR}/agent/mcp_client.js" --mock --mode="${MODE}" --node-id="${NODE_ID}" --json-only | \
    python3 "${SCRIPT_DIR}/agent/validator.py" --prompt "${SCRIPT_DIR}/agent/system_prompt.txt" --input - --json-only | \
    python3 "${SCRIPT_DIR}/execution/handler.py"
fi
