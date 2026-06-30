import os
import json
import platform
import psutil
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# 1. Initialize the High-Level FastMCP Server
# The name "Local System Monitor" will identify this server in the agent's tool logs.
mcp = FastMCP("Local System Monitor")

# 2. Define the Local Tool
# The docstring serves as the tool's description, which the Gemini model uses to understand when to call it.
@mcp.tool()
def get_system_metrics() -> str:
    """Retrieves real-time system metrics from the host machine, including CPU, memory, disk, and OS info.
    Use this to check if the local machine has enough resources or to understand its operating environment.
    """
    try:
        # Measure CPU usage over a 1-second interval
        cpu_pct = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        metrics = {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "cpu_percent": f"{cpu_pct}%",
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "memory_total_gb": f"{mem.total / (1024**3):.2f} GB",
            "memory_available_gb": f"{mem.available / (1024**3):.2f} GB",
            "memory_used_percent": f"{mem.percent}%",
            "disk_total_gb": f"{disk.total / (1024**3):.2f} GB",
            "disk_free_gb": f"{disk.free / (1024**3):.2f} GB",
            "disk_used_percent": f"{disk.percent}%"
        }
        return f"Local System Metrics:\n{json.dumps(metrics, indent=2)}"
    except Exception as e:
        return f"Error retrieving system metrics: {str(e)}"

# 3. Create a FastAPI instance to host the SSE endpoints
app = FastAPI(title="Local System Monitor MCP Server")

# 4. Mount the MCP SSE application
# This automatically registers GET /mcp/sse and POST /mcp/messages
app.mount("/mcp", mcp.sse_app())

if __name__ == "__main__":
    import uvicorn
    print("Starting Local System Monitor MCP Server on http://localhost:8000...")
    print("MCP SSE connection endpoint: http://localhost:8000/mcp/sse")
    print("MCP Message endpoint:        http://localhost:8000/mcp/messages")
    print("----------------------------------------------------------------")
    uvicorn.run(app, host="0.0.0.0", port=8000)
