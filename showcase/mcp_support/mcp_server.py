import os
import json
import platform
import psutil
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# 1. Initialize the High-Level FastMCP Server
mcp = FastMCP("Local System Monitor")

# 2. Define the Local Tool
@mcp.tool()
def get_system_metrics() -> str:
    """Retrieves real-time system metrics from the host machine, including CPU, memory, disk, and OS info.
    Use this to check if the local machine has enough resources or to understand its operating environment.
    """
    try:
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

# 3. Create FastAPI app
app = FastAPI(title="Local System Monitor MCP Server")

# 4. Request Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    print(f"\n--- INCOMING REQUEST ---")
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Body: {body.decode('utf-8', errors='ignore')}")
    response = await call_next(request)
    print(f"Response Status: {response.status_code}")
    print(f"------------------------\n")
    return response

# 5. Direct JSON-RPC over POST Fallback Handler
@app.post("/sse")
@app.post("/")
async def handle_json_rpc(request: Request):
    try:
        req_json = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
        
    method = req_json.get("method")
    req_id = req_json.get("id")
    
    print(f"[JSON-RPC] Received method: '{method}', ID: {req_id}")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "Local System Monitor",
                    "version": "0.1.0"
                }
            }
        }
    elif method == "notifications/initialized":
        return Response(status_code=200)
        
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_system_metrics",
                        "description": "Retrieves real-time system metrics from the host machine, including CPU, memory, disk, and OS info.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ]
            }
        }
    elif method == "tools/call":
        tool_params = req_json.get("params", {})
        tool_name = tool_params.get("name")
        if tool_name == "get_system_metrics":
            metrics_res = get_system_metrics()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": metrics_res
                        }
                    ]
                }
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {tool_name}"
                }
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

# 6. Mount the standard MCP SSE app to handle standard client routing
app.mount("/", mcp.sse_app())

if __name__ == "__main__":
    import uvicorn
    print("Starting Local System Monitor MCP Server on http://localhost:8000...")
    print("MCP SSE connection endpoint: http://localhost:8000/sse")
    print("MCP Message endpoint:        http://localhost:8000/messages")
    print("----------------------------------------------------------------")
    uvicorn.run(app, host="0.0.0.0", port=8000)
