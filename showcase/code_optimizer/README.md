# The Code Optimizer

This example showcases how the platform handles **server-side tool execution** (the secure Python Code Execution Sandbox) during a **real-time streaming interaction**. 

Because the Code Execution tool runs entirely on the Google Cloud backend, the developer script does not need to handle any tool execution loops—the platform automatically runs the code in its sandbox, observes the output, and streams the entire reasoning process back to the client.

It implements a modern, **event-driven streaming printer** that listens for `step.delta` events and prints both the model's text tokens and the sandbox's terminal outputs in real-time as they are generated.

## Flow Diagram

```mermaid
sequenceDiagram
    autonumber
    participant Script as Developer Script (Client)
    participant CP as Control Plane (GCP REST)
    participant DP as Data Plane (Interactions API)
    
    Script->>CP: Create Agent "code-optimizer-showcase" with Code Execution
    CP-->>Script: Return LRO (Poll until Ready)
    Script->>DP: Start Streaming Interaction: "Optimize this Fibonacci function"
    Note over DP: Agent writes & runs benchmark in cloud sandbox
    DP-->>Script: Streams thought process + benchmark outputs in real-time (StepDelta)
    Note over DP: Agent writes optimized code & runs comparative benchmark
    DP-->>Script: Streams final optimized code and speedup explanation
    Script->>CP: Delete Agent (Cleanup)
```

## How to Run

Ensure you have completed the main [setup](file:///Users/zhaofu/workspace/interactions_api/showcase/README.md#setup) first.

Run the script from the `showcase` directory:
```bash
python code_optimizer/code_optimizer.py
```
