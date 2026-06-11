#!/usr/bin/env node

/**
 * observability/mcp_server.js
 * Dynatrace MCP Server telemetry provider.
 * Listens on stdin for JSON-RPC resource requests, queries the Cloud Run instance,
 * and responds on stdout.
 */

const readline = require('readline');
const https = require('https');

const CLOUD_RUN_URL = 'https://ransafe-sandbox-453397284615.us-central1.run.app';

// Setup readline interface
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

/**
 * Fetches metrics from the Dynatrace API.
 * Returns a Promise resolving to the parsed telemetry payload.
 */
function fetchDynatraceMetrics(nodeId) {
  return new Promise((resolve, reject) => {
    const envUrl = process.env.DYNATRACE_ENV_URL;
    const token = process.env.DYNATRACE_API_TOKEN;

    if (!envUrl || !token) {
      return reject(new Error('Dynatrace environment variables not set'));
    }

    const baseUrl = envUrl.endsWith('/') ? envUrl.slice(0, -1) : envUrl;
    const cpuSelector = 'builtin:host.cpu.usage';
    const diskSelector = 'builtin:host.disk.writeOps';
    const metricSelector = `${cpuSelector},${diskSelector}`;
    const entitySelector = `type(HOST),entityId("${nodeId}")`;
    
    const queryUrl = `${baseUrl}/api/v2/metrics/query?metricSelector=${encodeURIComponent(metricSelector)}&entitySelector=${encodeURIComponent(entitySelector)}&pageSize=1`;

    const req = https.get(queryUrl, {
      headers: {
        'Authorization': `Api-Token ${token}`,
        'Accept': 'application/json'
      },
      timeout: 3000
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          if (res.statusCode !== 200) {
            return reject(new Error(`Dynatrace API returned HTTP ${res.statusCode}`));
          }
          const response = JSON.parse(data);
          let cpu = 25.0;
          let writes = 12;

          if (response.result) {
            for (const metricResult of response.result) {
              if (metricResult.metricId === cpuSelector && metricResult.data && metricResult.data.length > 0) {
                const values = metricResult.data[0].values;
                if (values && values.length > 0) {
                  cpu = values[values.length - 1];
                }
              }
              if (metricResult.metricId === diskSelector && metricResult.data && metricResult.data.length > 0) {
                const values = metricResult.data[0].values;
                if (values && values.length > 0) {
                  writes = Math.round(values[values.length - 1]);
                }
              }
            }
          }

          const entropy = writes > 200 ? 0.92 : 0.12;

          resolve({
            node_id: nodeId,
            metrics: {
              cpu_utilization_percentage: cpu,
              filesystem_write_ops_per_sec: writes,
              entropy_coefficient: entropy
            },
            timestamp: new Date().toISOString()
          });
        } catch (err) {
          reject(err);
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Dynatrace API timeout'));
    });
  });
}

/**
 * Fetches metrics from the Cloud Run URL.
 * Returns a Promise resolving to the parsed JSON payload.
 */
function fetchCloudMetrics() {
  return new Promise((resolve, reject) => {
    const req = https.get(CLOUD_RUN_URL, { timeout: 3000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          if (res.statusCode !== 200) {
            return reject(new Error(`HTTP status ${res.statusCode}`));
          }
          const payload = JSON.parse(data);
          resolve(payload);
        } catch (err) {
          reject(err);
        }
      });
    });

    req.on('error', (err) => {
      reject(err);
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });
  });
}

/**
 * Generates fallback/simulated metrics if Cloud Run is unreachable.
 */
function generateFallbackTelemetry(nodeId) {
  const isAttackMode = process.env.RANSOMWARE_TRIGGER === 'true';
  const cpu = isAttackMode ? 92.4 : 24.5;
  const writes = isAttackMode ? 480 : 15;
  const entropy = isAttackMode ? 0.941 : 0.182;

  return {
    node_id: nodeId,
    metrics: {
      cpu_utilization_percentage: cpu,
      filesystem_write_ops_per_sec: writes,
      entropy_coefficient: entropy
    },
    timestamp: new Date().toISOString()
  };
}

rl.on('line', async (line) => {
  if (!line.trim()) return;

  try {
    const request = JSON.parse(line);

    // Verify MCP resources/read method
    if (request.method === 'resources/read' && request.params && request.params.uri) {
      const uri = request.params.uri;
      const match = uri.match(/^dynatrace:\/\/nodes\/([^/]+)\/metrics$/);

      if (match) {
        const nodeId = match[1];
        let telemetry;

        try {
          if (process.env.RANSOMWARE_TRIGGER === 'true') {
            telemetry = generateFallbackTelemetry(nodeId);
            process.stderr.write(`[INFO] RANSOMWARE_TRIGGER active. Injecting simulated ransomware telemetry.\n`);
          } else if (process.env.DYNATRACE_ENV_URL && process.env.DYNATRACE_API_TOKEN) {
            process.stderr.write(`[INFO] Querying active Dynatrace environment at ${process.env.DYNATRACE_ENV_URL}...\n`);
            telemetry = await fetchDynatraceMetrics(nodeId);
          } else {
            // Attempt to pull metrics from the live Cloud Run endpoint
            telemetry = await fetchCloudMetrics();
            if (nodeId && nodeId !== 'metrics') {
              telemetry.node_id = nodeId;
            }
          }
        } catch (err) {
          // Fall back to local rules simulation if Cloud Run or Dynatrace is offline
          telemetry = generateFallbackTelemetry(nodeId);
          process.stderr.write(`[WARN] Telemetry fetch failed (${err.message}). Using local fallback telemetry.\n`);
        }

        const response = {
          jsonrpc: '2.0',
          id: request.id || 1,
          result: {
            contents: [
              {
                uri: uri,
                mimeType: 'application/json',
                text: JSON.stringify(telemetry)
              }
            ]
          }
        };

        console.log(JSON.stringify(response));
      } else {
        sendError(request.id, -32602, `Invalid resource URI: ${uri}`);
      }
    } else {
      sendError(request.id, -32601, `Method not supported: ${request.method}`);
    }
  } catch (err) {
    sendError(null, -32700, `Parse error: ${err.message}`);
  }
});

function sendError(id, code, message) {
  const errorResponse = {
    jsonrpc: '2.0',
    id: id,
    error: {
      code: code,
      message: message
    }
  };
  console.log(JSON.stringify(errorResponse));
}
