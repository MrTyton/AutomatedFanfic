# Model Context Protocol (MCP) Setup & Integration Guide

The AutomatedFanfic FastMCP server exposes system monitoring, diagnostics, queue inspection, and download control tools to AI coding agents and LLM clients (including Google Antigravity, Claude Desktop, and Claude Code).

---

## Architecture & Transports

The MCP server connects to AutomatedFanfic's FastAPI web API (`/api/debug/*`, `/api/health`, `/api/controls/*`) and provides two transport options:

1. **Stdio Transport**: Executed as a child process via `python -m mcp_server`. Communicates with the AI client over standard I/O (JSON-RPC) while forwarding calls to the AutomatedFanfic REST API over HTTP.
2. **Server-Sent Events (SSE) Transport**: Built directly into the running FastAPI web server at `/api/mcp/sse`. Any MCP client supporting SSE can connect over HTTP without launching a local Python subprocess.

### Prerequisites

Ensure the AutomatedFanfic web server is enabled in `config.toml`:

```toml
[web]
enabled = true
host = "0.0.0.0"
port = 8080
```

---

## Available MCP Tools

| Tool Name | Description | Key Arguments |
|:---|:---|:---|
| `get_system_overview` | System health, uptime, and process status | None |
| `inspect_coordinator_locks` | Coordinator worker domain locks and per-site backlogs | None |
| `inspect_queues` | Partitions active downloads into queued, processing, and waiting | None |
| `query_logs` | In-memory log buffer search and filtering | `level`, `component`, `search`, `limit` |
| `get_story_diagnostics` | Autopsy diagnostics for a URL (active status, history, Calibre, logs) | `url` |
| `inspect_calibre_book` | Query Calibre library metadata by ID, URL, or title | `query` |
| `test_calibre_connection` | Verify Calibre binary/library connection and CLI version | None |
| `test_antibot_status` | Check FlareSolverr proxy connectivity and Anubis solver readiness | None |
| `inspect_cookiejar` | Inspect loaded cookies for a site domain (masked tokens) | `domain` |
| `resolve_config_for_url` | Test FanFicFare configuration sections and strategy for URL | `url` |
| `test_email_connection` | Test IMAP email connectivity and check unread count | None |
| `test_notification` | Dispatch diagnostic test notification via Apprise | None |
| `simulate_email_parse` | Test URL parsing against raw email subject and body text | `subject`, `body` |
| `dry_run_fanfic_url` | Extract FanFicFare story metadata without downloading chapters | `url` |
| `inject_download` | Queue fanfiction URL with optional force re-download | `url`, `force` |
| `cancel_download` | Remove active or queued download | `url` |
| `retry_now` | Immediately trigger retry for a waiting URL | `url` |

---

## Configuration Snippets

### 1. Google Antigravity (`agy`)

Add the server to your Antigravity global MCP configuration at `~/.gemini/config/mcp_config.json`. The server schemas and guidance are stored under `~/.gemini/antigravity/mcp/automatedfanfic/`.

#### Stdio Transport (Windows)
```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "C:\\path\\to\\AutomatedFanfic\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\AutomatedFanfic\\root\\app",
        "AUTOMATEDFANFIC_API_URL": "http://localhost:8080/"
      }
    }
  }
}
```

#### Stdio Transport (Linux / macOS)
```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "/path/to/AutomatedFanfic/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/AutomatedFanfic/root/app",
        "AUTOMATEDFANFIC_API_URL": "http://localhost:8080/"
      }
    }
  }
}
```

#### Direct SSE Transport
```json
{
  "mcpServers": {
    "automatedfanfic": {
      "url": "http://localhost:8080/api/mcp/sse"
    }
  }
}
```

---

### 2. Visual Studio Code (`.vscode/mcp.json`)

Configure `.vscode/mcp.json` in the workspace root for VS Code and AI extensions (GitHub Copilot, Cline, Continue, Roo Code):

```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}/root/app",
        "AUTOMATEDFANFIC_API_URL": "http://localhost:8080/"
      }
    },
    "automatedfanfic-sse": {
      "url": "http://localhost:8080/api/mcp/sse"
    }
  }
}
```

---

### 3. Claude Desktop

Add to your `claude_desktop_config.json`:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

#### Windows Snippet
```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "C:\\path\\to\\AutomatedFanfic\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\AutomatedFanfic\\root\\app",
        "AUTOMATEDFANFIC_API_URL": "http://localhost:8080"
      }
    }
  }
}
```

#### Linux / macOS Snippet
```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "/path/to/AutomatedFanfic/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/AutomatedFanfic/root/app",
        "AUTOMATEDFANFIC_API_URL": "http://localhost:8080"
      }
    }
  }
}
```

---

### 3. Claude Code CLI

You can register the MCP server with the Claude Code CLI using `claude mcp add`.

#### Stdio Registration
```bash
# From within the AutomatedFanfic repository root
claude mcp add automatedfanfic -e PYTHONPATH=root/app -e AUTOMATEDFANFIC_API_URL=http://localhost:8080 -- python -m mcp_server
```

#### SSE Registration
```bash
# Connect to running AutomatedFanfic dashboard server
claude mcp add --transport sse automatedfanfic http://localhost:8080/api/mcp/sse
```

To verify registration in Claude Code:
```bash
claude mcp list
```

---

### 4. Docker Deployment Configuration

When AutomatedFanfic is deployed inside Docker, you have two primary options:

#### Option A: Direct SSE (Recommended)
Since the FastAPI web server mounts SSE at `/api/mcp/sse`, expose port `8080` and point your AI agent directly at the host:

```json
{
  "mcpServers": {
    "automatedfanfic": {
      "url": "http://<docker-host-or-ip>:8080/api/mcp/sse"
    }
  }
}
```

#### Option B: Stdio via `docker exec`
If your AI agent requires stdio transport and AutomatedFanfic runs inside a container named `automatedfanfic`:

```json
{
  "mcpServers": {
    "automatedfanfic": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "-e", "PYTHONPATH=/app/root/app",
        "-e", "AUTOMATEDFANFIC_API_URL=http://127.0.0.1:8080",
        "automatedfanfic",
        "python",
        "-m",
        "mcp_server"
      ]
    }
  }
}
```

#### Docker Compose Example
```yaml
services:
  automatedfanfic:
    container_name: automatedfanfic
    image: automatedfanfic:latest
    ports:
      - "8080:8080"
    volumes:
      - ./config.toml:/config/config.toml
      - ./calibre_library:/calibre
    environment:
      - AUTOMATEDFANFIC_CONFIG=/config/config.toml
    restart: unless-stopped
```

---

## Verification & Troubleshooting

### 1. Preflight API Connectivity Test
Before launching MCP clients, verify the AutomatedFanfic API is responding:

```powershell
# PowerShell
Invoke-RestMethod -Uri "http://localhost:8080/api/health"
```

```bash
# curl
curl -s http://localhost:8080/api/health
# Expected output: {"status":"ok"}
```

### 2. Verify SSE Endpoint
Test that the SSE endpoint is reachable with the required header:

```bash
curl -i -N -H "Accept: text/event-stream" http://localhost:8080/api/mcp/sse
# Expected status: 200 OK with content-type: text/event-stream
```

### 3. Verify Stdio Runner CLI
To test standard I/O communication from your shell:

```powershell
& .venv/Scripts/Activate.ps1
$env:PYTHONPATH="root/app"
$env:AUTOMATEDFANFIC_API_URL="http://localhost:8080"
python -m mcp_server
```

If the web API is unreachable, the CLI logs a clear diagnostic error and exits with code 1. When connected, it listens on stdio for JSON-RPC messages.
