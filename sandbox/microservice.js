const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const DB_DIR = path.join(__dirname, 'data', 'db');

// Ensure database directory exists
if (!fs.existsSync(DB_DIR)) {
  fs.mkdirSync(DB_DIR, { recursive: true });
}

// Generate a mock transaction
function generateTransaction() {
  const customers = ['Alice Smith', 'Bob Jones', 'Charlie Brown', 'Diana Prince', 'Evan Wright'];
  const statuses = ['COMPLETED', 'PENDING', 'PROCESSING'];
  const id = 'tx_' + Math.random().toString(36).substr(2, 9);
  
  return {
    transaction_id: id,
    timestamp: new Date().toISOString(),
    customer: customers[Math.floor(Math.random() * customers.length)],
    amount: parseFloat((Math.random() * 1000).toFixed(2)),
    status: statuses[Math.floor(Math.random() * statuses.length)]
  };
}

// Write a mock transaction log file
function writeTransactionLog() {
  const transaction = generateTransaction();
  const filename = `tx_${Date.now()}_${transaction.transaction_id}.log`;
  const filepath = path.join(DB_DIR, filename);
  
  try {
    fs.writeFileSync(filepath, JSON.stringify(transaction, null, 2), 'utf-8');
    console.log(`[Microservice] Organic write: Saved transaction ${transaction.transaction_id} to ${filename}`);
  } catch (err) {
    console.error(`[Microservice] Error writing transaction log:`, err);
  }
}

// Start continuous organic write operations (every 2.5 seconds)
console.log(`[Microservice] Starting organic transaction writer...`);
const writeInterval = setInterval(writeTransactionLog, 2500);

// HTTP Server
const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');

  if ((req.url === '/' || req.url === '') && req.method === 'GET') {
    let cpu = 24.5;
    let writes = 15;
    let entropy = 0.182;
    
    try {
      const files = fs.readdirSync(DB_DIR);
      const hasLocked = files.some(f => f.endsWith('.locked'));
      if (hasLocked) {
        cpu = 92.4;
        writes = 480;
        entropy = 0.941;
      }
    } catch (e) {}

    res.writeHead(200);
    res.end(JSON.stringify({
      node_id: 'ransafe-sandbox',
      metrics: {
        cpu_utilization_percentage: cpu,
        filesystem_write_ops_per_sec: writes,
        entropy_coefficient: entropy
      },
      timestamp: new Date().toISOString()
    }));
  } else if (req.url === '/health' && req.method === 'GET') {
    let fileCount = 0;
    try {
      fileCount = fs.readdirSync(DB_DIR).length;
    } catch (e) {}

    res.writeHead(200);
    res.end(JSON.stringify({
      status: 'UP',
      uptime: process.uptime(),
      pid: process.pid,
      metrics: {
        db_file_count: fileCount
      }
    }));
  } else if (req.url === '/transactions' && req.method === 'GET') {
    try {
      const files = fs.readdirSync(DB_DIR).filter(f => f.endsWith('.log'));
      const transactions = files.map(file => {
        try {
          const content = fs.readFileSync(path.join(DB_DIR, file), 'utf-8');
          return JSON.parse(content);
        } catch (e) {
          return { file, error: 'Encrypted or unreadable' };
        }
      });
      res.writeHead(200);
      res.end(JSON.stringify(transactions));
    } catch (err) {
      res.writeHead(500);
      res.end(JSON.stringify({ error: 'Failed to read transactions' }));
    }
  } else {
    res.writeHead(404);
    res.end(JSON.stringify({ error: 'Not Found' }));
  }
});

server.listen(PORT, () => {
  console.log(`[Microservice] Victim service running on port ${PORT} (PID: ${process.pid})`);
});

// Handle shutdown
process.on('SIGTERM', () => {
  console.log('[Microservice] Shutting down...');
  clearInterval(writeInterval);
  server.close(() => {
    process.exit(0);
  });
});
