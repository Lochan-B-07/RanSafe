import sys
import json
import os
import subprocess
from datetime import datetime
import threading
import time
import socket
import http.server
import socketserver
import re

# Try to import Google Cloud Secret Manager for auth validation
try:
    from google.cloud import secretmanager
    HAS_GCP_SECRET_MANAGER = True
except ImportError:
    HAS_GCP_SECRET_MANAGER = False

# Try to import Rich library for advanced TUI
try:
    import rich
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.console import Console
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ANSI Colors (Fallback)
RESET = "\033[0m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"

# Path to the schema
EXECUTION_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../docs/execution_interface.json")

BANNER = f"""{RED}{BOLD}
  ____             ____              __ 
 |  _ \\  __ _ _ __/ ___|  __ _  ___ / _| ___
 | |_) |/ _` | '_ \\___ \\ / _` |/ _ \\ |_ / _ \\
 |  _ <| (_| | | | |___) | (_| |  __/  _|  __/
 |_| \\_\\\\__,_|_| |_|____/ \\__,_|\\___|_|  \\___|
{RESET}"""

# Global State Dictionary for the Orchestrator
state = {
    "status": "NOMINAL", # NOMINAL, PENDING_CONFIRMATION, AIRGAP_ACTIVE, REALLOCATE_RESOURCES, MONITOR_INTENSE
    "target_node_id": "k8s-pod-node-dummy-app-xyz",
    "authorization_token": "",
    "reasoning_summary": "",
    "metrics": {
        "cpu_utilization_percentage": 0.0,
        "filesystem_write_ops_per_sec": 0,
        "entropy_coefficient": 0.0
    },
    "logs": []
}

state_lock = threading.Lock()
confirm_event = threading.Event()
cancel_event = threading.Event()

PORT = 8080

# Live TUI Controller
live_display = None
live_started = False

def start_live_display():
    global live_started
    if HAS_RICH and live_display and not live_started:
        try:
            live_display.start()
            live_started = True
        except Exception:
            pass

def stop_live_display():
    global live_started
    if HAS_RICH and live_display and live_started:
        try:
            live_display.stop()
            live_started = False
        except Exception:
            pass

def get_circular_gauge(percent):
    """Returns a quadrant circle unicode character based on progress."""
    if percent < 12.5:
        return "○"
    elif percent < 37.5:
        return "◔"
    elif percent < 62.5:
        return "◑"
    elif percent < 87.5:
        return "◕"
    else:
        return "●"

def make_circular_gauge_str(value, max_val, color):
    """Draws a compact circular representation next to a colored horizontal block bar."""
    pct = min(int((value / max_val) * 100), 100)
    gauge_char = get_circular_gauge(pct)
    filled_bars = int(pct / 10)
    bar = "▰" * filled_bars + "▱" * (10 - filled_bars)
    return f"[{color}]{gauge_char} {bar}[/{color}] {pct}%"

def make_layout():
    """Generates the Rich TUI layout dynamically from global state."""
    layout = Layout()
    
    # Split into header, body, footer
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=8)
    )
    
    # Split body into left and right panels
    layout["body"].split_row(
        Layout(name="left_panel", ratio=1),
        Layout(name="right_panel", ratio=1)
    )
    
    # Header Panel
    title_text = Text("🛡️  RANSAFE SRE ORCHESTRATOR — ACTIVE CONTAINMENT ENGINE", style="bold cyan", justify="center")
    layout["header"].update(Panel(title_text, border_style="cyan"))
    
    # Left Panel: System Status & Telemetry
    status_table = Table.grid(expand=True)
    status_table.add_column(style="bold white", width=18)
    status_table.add_column()
    
    status_val = state["status"]
    if status_val == "NOMINAL":
        status_styled = "[bold green]NOMINAL[/bold green]"
    elif status_val == "PENDING_CONFIRMATION":
        status_styled = "[bold yellow flashing]PENDING CONFIRMATION[/bold yellow flashing]"
    elif status_val == "AIRGAP_ACTIVE" or status_val == "AIRGAP_NODE":
        status_styled = "[bold red flashing]AIRGAP ACTIVE[/bold red flashing]"
    elif status_val == "MONITOR_INTENSE":
        status_styled = "[bold yellow]MONITOR INTENSE[/bold yellow]"
    elif status_val == "REALLOCATE_RESOURCES":
        status_styled = "[bold green]SCALING ACTIVE[/bold green]"
    else:
        status_styled = f"[bold yellow]{status_val}[/bold yellow]"
        
    status_table.add_row("System Status:", status_styled)
    status_table.add_row("Target Node:", f"[yellow]{state['target_node_id']}[/yellow]")
    status_table.add_row("Auth Token:", f"[magenta]{state['authorization_token'] if state['authorization_token'] else 'N/A'}[/magenta]")
    
    metrics_table = Table.grid(expand=True)
    metrics_table.add_column(style="bold white", width=18)
    metrics_table.add_column()
    
    cpu = state["metrics"]["cpu_utilization_percentage"]
    writes = state["metrics"]["filesystem_write_ops_per_sec"]
    entropy = state["metrics"]["entropy_coefficient"]
    
    metrics_table.add_row("CPU Load:", make_circular_gauge_str(cpu, 100, "green" if cpu < 70 else "yellow" if cpu < 85 else "red"))
    metrics_table.add_row("Write Ops/s:", make_circular_gauge_str(writes, 1000, "green" if writes < 150 else "yellow" if writes < 300 else "red"))
    metrics_table.add_row("Entropy Coeff:", make_circular_gauge_str(entropy * 100, 100, "green" if entropy < 0.5 else "yellow" if entropy < 0.8 else "red"))
    
    left_grid = Table.grid(expand=True)
    left_grid.add_row(Panel(status_table, title="System Status Grid", border_style="cyan"))
    left_grid.add_row(Panel(metrics_table, title="Telemetry Metric Gauges", border_style="cyan"))
    layout["left_panel"].update(left_grid)
    
    # Right Panel: Containment Checklist & AI Reasoning
    steps_table = Table.grid(expand=True)
    steps_table.add_column(width=4)
    steps_table.add_column()
    
    logs_str = "\n".join(state["logs"])
    steps_list = [
        ("Cloud Armor IP Policy", ["CLOUD ARMOR", "security-policies"]),
        ("VPC Firewall Block", ["VPC FIREWALL", "firewall-rules"]),
        ("GCP IAM SA Revocation", ["GCP IAM", "remove-iam-policy-binding"]),
        ("GKE Compromised Pod Eviction", ["GKE CONTAINER OPS", "delete pod"]),
        ("GKE Replica Workload Rollout", ["GKE REPLICATOR", "rollout restart"])
    ]
    
    for label, keywords in steps_list:
        matched = False
        success = False
        error = False
        for kw in keywords:
            if kw in logs_str:
                matched = True
                if any(x in logs_str for x in ["Success", "✅", "successfully", "started"]):
                    success = True
                elif "ERROR" in logs_str or "❌" in logs_str:
                    error = True
        
        if success:
            icon = "[bold green]✓[/bold green]"
            item_label = f"[green]{label}[/green]"
        elif error:
            icon = "[bold red]✗[/bold red]"
            item_label = f"[red]{label}[/red]"
        elif matched:
            icon = "[bold yellow]⏳[/bold yellow]"
            item_label = f"[yellow]{label}[/yellow]"
        else:
            icon = "[white]○[/white]"
            item_label = f"[dim white]{label}[/dim white]"
            
        steps_table.add_row(icon, item_label)
        
    reasoning_panel = Panel(
        Text(state["reasoning_summary"] if state["reasoning_summary"] else "Continuous observation active. Monitoring workloads.", style="italic white"),
        title="AI Reasoning Summary",
        border_style="cyan"
    )
    
    right_grid = Table.grid(expand=True)
    right_grid.add_row(Panel(steps_table, title="Emergency Containment Steps", border_style="cyan"))
    right_grid.add_row(reasoning_panel)
    layout["right_panel"].update(right_grid)
    
    # Footer Panel: Console Logs
    log_text = Text()
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    
    for log in state["logs"][-5:]: # Show last 5 logs
        clean_log = ansi_escape.sub('', log)
        if "[INFO]" in clean_log:
            log_text.append(clean_log + "\n", style="blue")
        elif "[WARN]" in clean_log:
            log_text.append(clean_log + "\n", style="yellow")
        elif "[ERROR]" in clean_log:
            log_text.append(clean_log + "\n", style="red")
        elif "[SUCCESS]" in clean_log:
            log_text.append(clean_log + "\n", style="green")
        else:
            log_text.append(clean_log + "\n", style="white")
            
    layout["footer"].update(Panel(log_text, title="Live Execution Logs", border_style="cyan"))
    
    return layout

def update_tui(action=None, target=None, token=None, reasoning=None):
    """Triggers a TUI refresh, falling back to ANSI if Rich is not imported."""
    if HAS_RICH and live_display and live_started:
        try:
            live_display.update(make_layout())
        except Exception:
            pass
    else:
        # Fallback to custom ANSI renderer
        with state_lock:
            render_ui(
                action if action else state["status"], 
                target if target else state["target_node_id"], 
                token if token else state["authorization_token"], 
                reasoning if reasoning else state["reasoning_summary"], 
                state["logs"]
            )

def log_info(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with state_lock:
        state["logs"].append(f"{BLUE}[{timestamp}] [INFO] {msg}{RESET}")
    update_tui()

def log_warn(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with state_lock:
        state["logs"].append(f"{YELLOW}[{timestamp}] [WARN] {msg}{RESET}")
    update_tui()

def log_err(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with state_lock:
        state["logs"].append(f"{RED}[{timestamp}] [ERROR] {msg}{RESET}")
    update_tui()

def log_success(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with state_lock:
        state["logs"].append(f"{GREEN}[{timestamp}] [SUCCESS] {msg}{RESET}")
    update_tui()

def render_ui(action, target, token="", reasoning="", logs=[]):
    """Clears screen and draws a high-fidelity, colored fallback console."""
    os.system('clear' if os.name == 'posix' else 'cls')
    print(BANNER)
    print(f"{CYAN}{BOLD}=" * 80 + f"{RESET}")
    print(f" {WHITE}{BOLD}🛡️  RANSAFE SRE ORCHESTRATOR — ACTIVE CONTAINMENT ENGINE  🛡️{RESET}")
    print(f"{CYAN}=" * 80 + f"{RESET}")
    
    module = f"{BLUE}execution/handler.py (Core Engine){RESET}"
    monitored_node = f"{YELLOW}{target}{RESET}"
    auth_token = f"{MAGENTA}{token if token else 'N/A'}{RESET}"
    
    if action == "AIRGAP_NODE" or action == "AIRGAP_ACTIVE":
        action_str = f"{RED}{BOLD}AIRGAP_NODE{RESET}"
        switch_str = f"{BG_RED}{WHITE}{BOLD} 🚨 OPENED - CRITICAL ANOMALY AIRGAP ACTIVE {RESET}"
        integrity_str = f"{RED}{BOLD}🔥 ATTACK VECTOR MITIGATED IN REAL-TIME{RESET}"
    elif action == "PENDING_CONFIRMATION":
        action_str = f"{RED}{BOLD}PENDING_CONFIRMATION{RESET}"
        switch_str = f"{BG_RED}{WHITE}{BOLD} ⚠️  AWAITING OPERATOR CONTAINER OVERRIDE ACTION {RESET}"
        integrity_str = f"{RED}{BOLD}⚠️ SUSPECTED ACTIVE RANSOMWARE ENCRYPTION FLOW{RESET}"
    elif action == "REALLOCATE_RESOURCES":
        action_str = f"{GREEN}{BOLD}REALLOCATE_RESOURCES{RESET}"
        switch_str = f"{BG_YELLOW}{WHITE}{BOLD} 🟢 CLOSED - ACTIVE RESOURCE AUTOMATION {RESET}"
        integrity_str = f"{YELLOW}{BOLD}📈 HIGH PRODUCTION WORKLOAD BALANCING{RESET}"
    elif action == "MONITOR_INTENSE":
        action_str = f"{YELLOW}{BOLD}MONITOR_INTENSE{RESET}"
        switch_str = f"{BG_YELLOW}{WHITE}{BOLD} ⚠️ WARN - HIGH FREQUENCY OBSERVABILITY {RESET}"
        integrity_str = f"{CYAN}{BOLD}🔍 DEEPER METRIC SIGNATURE ANALYSIS{RESET}"
    else:
        action_str = f"{CYAN}{BOLD}NOMINAL / AWAITING PAYLOAD{RESET}"
        switch_str = f"{BG_GREEN}{WHITE}{BOLD} 🟢 CLOSED - STEADY NOMINAL STATE {RESET}"
        integrity_str = f"{GREEN}{BOLD}✅ NO MALICIOUS DISK BEHAVIOR DETECTED{RESET}"

    print(f" {BOLD}• CONTEXT MODULE{RESET}   : {module}")
    print(f" {BOLD}• MONITORED NODE{RESET}   : {monitored_node}")
    print(f" {BOLD}• AUTH TOKEN{RESET}       : {auth_token}")
    print(f" {BOLD}• DISPATCH ACTION{RESET}  : {action_str}")
    print(f" {BOLD}• CIRCUIT SWITCH{RESET}   : {switch_str}")
    print(f" {BOLD}• SYSTEM INTEGRITY{RESET} : {integrity_str}")
    print(f"{CYAN}-" * 80 + f"{RESET}")
    
    if reasoning:
        print(f" {BOLD}🧠 AI REASONING SUMMARY:{RESET}")
        print(f"  \"{ITALIC}{WHITE}{reasoning}{RESET}\"")
        print(f"{CYAN}-" * 80 + f"{RESET}")
        
    print(f" {BOLD}📜 LIVE EXECUTION LOG PIPELINE:{RESET}")
    if logs:
        for log in logs[-8:]:
            print(f"  {log}")
    else:
        print(f"  {BLUE}[INFO] Pipeline active. Awaiting autonomous evaluation matrix...{RESET}")
    print(f"{CYAN}=" * 80 + f"{RESET}")

def execute_airgap(target_asset, action_token, auth_token, ai_reasoning):
    log_info(f"Routing action {action_token} to airgap_rules.sh...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    airgap_script = os.path.join(script_dir, "airgap_rules.sh")
    
    try:
        os.chmod(airgap_script, 0o755)
    except Exception:
        pass
    
    proc = subprocess.run(
        [airgap_script, target_asset, action_token, auth_token, ai_reasoning],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    for outline in proc.stdout.splitlines():
        if outline.strip():
            if "Success" in outline or "verified" in outline or "✅" in outline:
                log_success(outline.strip())
            elif "ERROR" in outline or "❌" in outline:
                log_err(outline.strip())
            elif "WARNING" in outline or "⚠️" in outline:
                log_warn(outline.strip())
            else:
                log_info(outline.strip())
                
    for errline in proc.stderr.splitlines():
        if errline.strip():
            log_err(errline.strip())
            
    if proc.returncode == 0:
        log_success(f"Execution engine successfully applied action: {action_token}")
    else:
        log_err(f"Execution script exited with error code {proc.returncode}")

def execute_restore(target_asset):
    log_info(f"Routing recovery request to restore_network.sh for node '{target_asset}'...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    restore_script = os.path.join(script_dir, "restore_network.sh")
    
    try:
        os.chmod(restore_script, 0o755)
    except Exception:
        pass
    
    proc = subprocess.run(
        [restore_script, target_asset],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    for outline in proc.stdout.splitlines():
        if outline.strip():
            if "Success" in outline or "verified" in outline or "✅" in outline:
                log_success(outline.strip())
            elif "ERROR" in outline or "❌" in outline:
                log_err(outline.strip())
            elif "WARNING" in outline or "⚠️" in outline:
                log_warn(outline.strip())
            else:
                log_info(outline.strip())
                
    for errline in proc.stderr.splitlines():
        if errline.strip():
            log_err(errline.strip())
            
    if proc.returncode == 0:
        log_success(f"Network recovery completed for {target_asset}")
        with state_lock:
            state["status"] = "NOMINAL"
        update_tui()
    else:
        log_err(f"Restore script exited with error code {proc.returncode}")

def validate_gcp_secret(auth_token):
    """
    Validates the authorization token against Google Cloud Secret Manager.
    If GCP is not active or secretmanager is not installed, it falls back to passing.
    """
    if not HAS_GCP_SECRET_MANAGER:
        log_info("google-cloud-secret-manager not installed. Skipping direct Python validation.")
        return True
        
    try:
        # Check if running in GCP context
        project_id = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            # Try to get project via gcloud config
            import subprocess
            res = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            project_id = res.stdout.strip()
            
        if not project_id:
            log_warn("GCP Project ID not detected. Skipping Secret Manager validation.")
            return True

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/ransafe-auth-key/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_val = response.payload.data.decode("UTF-8").strip()
        
        if auth_token != secret_val:
            log_err("Security token verification failed against GCP Secret Manager!")
            return False
            
        log_success("Security token successfully validated against GCP Secret Manager.")
        return True
    except Exception as e:
        log_warn(f"Secret Manager validation bypassed due to: {e}")
        return True

class RanSafeWebServer(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/events":
            self.handle_sse()
        elif self.path == "/" or self.path == "/index.html":
            self.serve_file("index.html", "text/html")
        elif self.path == "/style.css":
            self.serve_file("style.css", "text/css")
        elif self.path == "/app.js":
            self.serve_file("app.js", "application/javascript")
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        if self.path == "/api/confirm":
            confirm_event.set()
            self.send_json_response({"status": "success", "message": "Airgap action confirmed"})
        elif self.path == "/api/cancel":
            cancel_event.set()
            self.send_json_response({"status": "success", "message": "Airgap action cancelled"})
        elif self.path == "/api/restore":
            target = None
            with state_lock:
                target = state["target_node_id"]
            if target:
                threading.Thread(target=execute_restore, args=(target,), daemon=True).start()
                self.send_json_response({"status": "success", "message": f"Network restoration triggered for {target}"})
            else:
                self.send_json_response({"status": "error", "message": "No target node active for restoration"}, 400)
        else:
            self.send_error(404, "API Endpoint Not Found")

    def serve_file(self, filename, content_type):
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        filepath = os.path.join(web_dir, filename)
        if not os.path.exists(filepath):
            self.send_error(404, f"{filename} Not Found")
            return
        
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

    def send_json_response(self, data, status=200):
        try:
            content = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            pass

    def handle_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        while True:
            try:
                with state_lock:
                    clean_logs = [ansi_escape.sub('', log) for log in state["logs"]]
                    state_data = {
                        "status": state["status"],
                        "target_node_id": state["target_node_id"],
                        "authorization_token": state["authorization_token"],
                        "reasoning_summary": state["reasoning_summary"],
                        "metrics": state["metrics"],
                        "logs": clean_logs
                    }
                payload = f"data: {json.dumps(state_data)}\n\n"
                self.wfile.write(payload.encode('utf-8'))
                self.wfile.flush()
            except (socket.error, ConnectionResetError, BrokenPipeError):
                break
            time.sleep(0.5)

def start_web_server():
    server_address = ('', PORT)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(server_address, RanSafeWebServer) as httpd:
        log_info(f"Web Dashboard server running on http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    try:
        import jsonschema
        HAS_JSONSCHEMA = True
    except ImportError:
        HAS_JSONSCHEMA = False

    try:
        with open(EXECUTION_SCHEMA_PATH, "r") as f:
            EXECUTION_SCHEMA = json.load(f)
    except Exception as e:
        EXECUTION_SCHEMA = None
        log_warn(f"Could not load execution interface schema: {e}")

    # Initialize Live TUI
    if HAS_RICH:
        console = Console()
        live_display = Live(make_layout(), console=console, screen=True, auto_refresh=True, refresh_per_second=4)

    log_info("RanSafe Execution Orchestrator Daemon initialized.")
    
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    
    start_live_display()
    update_tui()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line.strip())
            
            # Validate schema
            if HAS_JSONSCHEMA and EXECUTION_SCHEMA:
                try:
                    jsonschema.validate(instance=payload, schema=EXECUTION_SCHEMA)
                    log_success("Payload successfully validated against execution_interface.json schema.")
                except jsonschema.exceptions.ValidationError as ve:
                    log_err(f"Schema Validation Failed: {ve.message}")
                    update_tui("NOMINAL", "unknown-node")
                    continue
            else:
                required = ["action", "target_node_id", "authorization_token", "reasoning_summary"]
                missing = [f for f in required if f not in payload]
                if missing:
                    log_err(f"Payload missing required fields: {missing}")
                    update_tui("NOMINAL", "unknown-node")
                    continue

            action_token = payload.get("action")
            target_asset = payload.get("target_node_id")
            auth_token = payload.get("authorization_token")
            ai_reasoning = payload.get("reasoning_summary")
            metrics = payload.get("metrics", {
                "cpu_utilization_percentage": 0.0,
                "filesystem_write_ops_per_sec": 0,
                "entropy_coefficient": 0.0
            })
            
            with state_lock:
                state["target_node_id"] = target_asset
                state["authorization_token"] = auth_token
                state["reasoning_summary"] = ai_reasoning
                state["metrics"] = metrics
            
            update_tui()
            
            if action_token in ["AIRGAP_NODE", "REALLOCATE_RESOURCES", "MONITOR_INTENSE"]:
                # Verify token against Secret Manager before proceeding
                if not validate_gcp_secret(auth_token):
                    log_err(f"Action {action_token} rejected due to unauthorized access token.")
                    continue

                if action_token == "AIRGAP_NODE":
                    confirm_event.clear()
                    cancel_event.clear()
                    
                    with state_lock:
                        state["status"] = "PENDING_CONFIRMATION"
                    update_tui()
                    
                    # Stop TUI to prompt on TTY
                    stop_live_display()
                    
                    def prompt_terminal():
                        print(f"\n{YELLOW}{BOLD}⚠️  [ACTION REQUIRED] AI has recommended network isolation (AIRGAP_NODE) for node '{target_asset}'.{RESET}")
                        print(f"{YELLOW}Reasoning: {ai_reasoning}{RESET}")
                        print(f"{WHITE}Confirm isolation? (y/n) [Default: y]: {RESET}", end="", flush=True)
                        try:
                            with open('/dev/tty', 'r') as tty:
                                choice = tty.readline().strip().lower()
                        except Exception:
                            choice = input().strip().lower()
                        
                        if choice in ['n', 'no']:
                            cancel_event.set()
                        else:
                            confirm_event.set()

                    t_prompt = threading.Thread(target=prompt_terminal, daemon=True)
                    t_prompt.start()
                    
                    while not confirm_event.is_set() and not cancel_event.is_set():
                        time.sleep(0.1)
                        
                    # Restart TUI
                    start_live_display()
                    
                    if confirm_event.is_set():
                        with state_lock:
                            state["status"] = "AIRGAP_ACTIVE"
                        execute_airgap(target_asset, action_token, auth_token, ai_reasoning)
                        update_tui()
                        
                        # Stop TUI to check restore
                        stop_live_display()
                        
                        def prompt_restore():
                            print(f"\n{RED}{BOLD}🚨 [AIRGAP ACTIVE] Node '{target_asset}' is isolated.{RESET}")
                            print(f"{WHITE}Press [R] to trigger restore_network.sh and recover system, or [Q] to quit: {RESET}", end="", flush=True)
                            try:
                                with open('/dev/tty', 'r') as tty:
                                    choice = tty.readline().strip().lower()
                            except Exception:
                                choice = input().strip().lower()
                            
                            if choice in ['r', 'restore']:
                                execute_restore(target_asset)
                            elif choice in ['q', 'quit']:
                                sys.exit(0)

                        t_res = threading.Thread(target=prompt_restore, daemon=True)
                        t_res.start()
                        
                        # Wait for restore
                        while True:
                            with state_lock:
                                current_status = state["status"]
                            if current_status == "NOMINAL":
                                break
                            time.sleep(0.2)
                            
                        start_live_display()
                        update_tui()
                    else:
                        with state_lock:
                            state["status"] = "NOMINAL"
                        log_warn("Airgap isolation cancelled by operator override.")
                        update_tui()
                else:
                    with state_lock:
                        state["status"] = action_token
                    execute_airgap(target_asset, action_token, auth_token, ai_reasoning)
                    update_tui()
            else:
                log_warn(f"Received unknown action code: {action_token}. No state mutation triggered.")
                update_tui()
                
        except json.JSONDecodeError:
            log_err("Received malformed non-JSON data stream.")
            update_tui("NOMINAL", "unknown-node")
            continue
            
    # Stop TUI on exit
    stop_live_display()