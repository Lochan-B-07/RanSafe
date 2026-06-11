#!/usr/bin/env node

/**
 * mcp_client.js
 * Interconnects the Dynatrace MCP Server hosted by Lane 2 with RanSafe's reasoning core.
 * Adheres to low CPU overhead guidelines and enforces strict input telemetry contracts.
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const TELEMETRY_SCHEMA_PATH = path.join(__dirname, '../docs/telemetry_schema.json');

// Load schema for manual verification (to keep execution package-free and extremely fast)
let telemetrySchema;
try {
  telemetrySchema = JSON.parse(fs.readFileSync(TELEMETRY_SCHEMA_PATH, 'utf8'));
} catch (err) {
  console.error('[ERROR] Could not load telemetry schema:', err.message);
  process.exit(1);
}

/**
 * Validates telemetry payload against docs/telemetry_schema.json guidelines.
 * Throws explicit errors on mismatch to prevent memory leaks or bad state propagation.
 */
function validateTelemetry(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Payload must be an object');
  }
  if (typeof payload.node_id !== 'string') {
    throw new Error('Invalid or missing node_id');
  }
  if (typeof payload.timestamp !== 'string') {
    throw new Error('Invalid or missing timestamp');
  }
  if (!payload.metrics || typeof payload.metrics !== 'object') {
    throw new Error('Invalid or missing metrics object');
  }

  const { cpu_utilization_percentage, filesystem_write_ops_per_sec, entropy_coefficient } = payload.metrics;
  if (typeof cpu_utilization_percentage !== 'number') {
    throw new Error('metrics.cpu_utilization_percentage must be a number');
  }
  if (!Number.isInteger(filesystem_write_ops_per_sec)) {
    throw new Error('metrics.filesystem_write_ops_per_sec must be an integer');
  }
  if (typeof entropy_coefficient !== 'number') {
    throw new Error('metrics.entropy_coefficient must be a number');
  }
  return true;
}

/**
 * Query Dynatrace MCP Server using MCP protocol over stdio.
 */
function queryMcpServerStdio(serverPath, nodeId) {
  return new Promise((resolve, reject) => {
    // Spawn Lane 2 Dynatrace MCP server
    const server = spawn('node', [serverPath]);
    let stdoutBuffer = '';
    let stderrBuffer = '';

    server.stdout.on('data', (data) => {
      stdoutBuffer += data.toString();
    });

    server.stderr.on('data', (data) => {
      stderrBuffer += data.toString();
    });

    server.on('error', (err) => {
      reject(new Error(`Failed to start MCP server process: ${err.message}`));
    });

    server.on('close', (code) => {
      if (code !== 0) {
        return reject(new Error(`MCP Server process exited with code ${code}. Error: ${stderrBuffer}`));
      }
      try {
        const response = JSON.parse(stdoutBuffer.trim());
        resolve(response);
      } catch (err) {
        reject(new Error(`Failed to parse MCP JSON-RPC response: ${err.message}`));
      }
    });

    // Send MCP JSON-RPC request for reading the metric resource
    const request = {
      jsonrpc: '2.0',
      id: 1,
      method: 'resources/read',
      params: {
        uri: `dynatrace://nodes/${nodeId}/metrics`
      }
    };

    server.stdin.write(JSON.stringify(request) + '\n');
    server.stdin.end();
  });
}

/**
 * Mock response generator when Lane 2 Dynatrace MCP server is offline.
 */
function getMockDynatraceMcpMetrics(nodeId, mode = 'ransomware') {
  if (mode === 'normal') {
    return {
      node_id: nodeId,
      metrics: {
        cpu_utilization_percentage: 24.5,
        filesystem_write_ops_per_sec: 15,
        entropy_coefficient: 0.182
      },
      timestamp: new Date().toISOString()
    };
  } else if (mode === 'reallocate') {
    return {
      node_id: nodeId,
      metrics: {
        cpu_utilization_percentage: 78.4,
        filesystem_write_ops_per_sec: 22,
        entropy_coefficient: 0.150
      },
      timestamp: new Date().toISOString()
    };
  }
  return {
    node_id: nodeId,
    metrics: {
      cpu_utilization_percentage: 92.4,
      filesystem_write_ops_per_sec: 480,
      entropy_coefficient: 0.941
    },
    timestamp: new Date().toISOString()
  };
}

// Command Line Interface & Module Exports
if (require.main === module) {
  const args = process.argv.slice(2);
  const nodeIdArg = args.find(arg => arg.startsWith('--node-id='))?.split('=')[1] || 'node-us-east-412';
  const serverPathArg = args.find(arg => arg.startsWith('--server-path='))?.split('=')[1];
  const modeArg = args.find(arg => arg.startsWith('--mode='))?.split('=')[1] || 'ransomware';
  const mockMode = args.includes('--mock') || !serverPathArg;
  const jsonOnly = args.includes('--json-only');

  if (mockMode) {
    const liveUrl = 'https://ransafe-sandbox-453397284615.us-central1.run.app';
    if (!jsonOnly) {
      console.log(`[INFO] Running in MCP Client mode fetching from live HTTP endpoint: ${liveUrl}`);
    }
    fetch(liveUrl)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        return res.json();
      })
      .then(payload => {
        validateTelemetry(payload);
        if (!jsonOnly) {
          console.log('✓ Live Telemetry retrieved successfully:');
          console.log(JSON.stringify(payload, null, 2));
        } else {
          console.log(JSON.stringify(payload));
        }
      })
      .catch(err => {
        console.error('✗ Telemetry retrieval/validation failed:', err.message);
        process.exit(1);
      });
  } else {
    if (!jsonOnly) {
      console.log(`[INFO] Connecting to Dynatrace MCP Server: ${serverPathArg}`);
    }
    queryMcpServerStdio(serverPathArg, nodeIdArg)
      .then(response => {
        // Map response to telemetry schema if nested differently
        // In MCP standard, response.result.contents[0].text contains stringified resource or JSON
        let payload;
        try {
          if (response.result && response.result.contents && response.result.contents[0]) {
            payload = JSON.parse(response.result.contents[0].text);
          } else {
            payload = response;
          }
        } catch (err) {
          throw new Error(`MCP result not in expected format: ${err.message}`);
        }

        validateTelemetry(payload);
        if (!jsonOnly) {
          console.log('✓ Telemetry retrieved from MCP Server and verified successfully:');
          console.log(JSON.stringify(payload, null, 2));
        } else {
          console.log(JSON.stringify(payload));
        }
      })
      .catch(err => {
        console.error('✗ MCP Retrieval failed:', err.message);
        process.exit(1);
      });
  }
} else {
  module.exports = {
    validateTelemetry,
    getMockDynatraceMcpMetrics
  };
}

