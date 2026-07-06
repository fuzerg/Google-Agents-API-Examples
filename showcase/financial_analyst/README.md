# The Smart Financial Analyst

This example demonstrates how to combine **server-side tools** (Google Search), a **custom GCS-mounted skill**, and a **GCS-mounted output path** in an autonomous background interaction. The agent uses Google Search to find live stock prices and news, analyzes them, and uses the custom `financial_analyst` skill (loading helper scripts located under `/.agents/skills/financial_analyst/scripts/`) to generate a beautiful PDF report.

---

## How It Works

```
 ┌──────────────────────┐
 │     Local Client     │
 │ (Unified prober.py)  │
 └──────────┬───────────┘
            │
            │ (1) Creates custom agent with GCS-mounted skill + output GCS Fuse
            │ (2) Starts background interaction: "Compare GOOG and MSFT"
            ▼
 ┌────────────────────────────────────────────────────────┐
 │                   Gemini Agent Platform                 │
 │                                                        │
 │  ┌──────────────────────────────────────────────────┐  │
 │  │              Agent Container (Cloud)             │  │
 │  │                                                  │  │
 │  │ (3) Resolves news via Google Search tool         │  │
 │  │ (4) Executes python script via code execution:   │  │
 │  │     - Imports stock & PDF helpers from skill     │  │
 │  │     - Writes final report to /workspace/output/  │  │
 │  │                                                  │  │
 │  └───────────────────────┬──────────────────────────┘  │
 └──────────────────────────┼─────────────────────────────┘
                            │
                            │ (5) GCS Fuse automatically uploads PDF in real-time
                            ▼
                  ┌───────────────────┐
                  │ GCS Output Folder │
                  │  (GCS Bucket)     │
                  └─────────┬─────────┘
                            │
                            │ (6) Downloads output PDF locally
                            ▼
                 ┌─────────────────────┐
                 │ Local Output Folder │
                 └─────────────────────┘
```

1.  **Provisioning & GCS Upload**: The prober script uploads the custom Python helper scripts (`stock_helper.py` and `pdf_helper.py`) and instructions (`SKILL.md`) to your GCS bucket.
2.  **Custom Agent Deployment**: The Control Plane registers the agent configuration in the cloud, specifying:
    - GCS mount `gs://[BUCKET]/financial_analyst` to `/.agents/skills/financial_analyst` (read-only skill resources).
    - GCS mount `gs://[BUCKET]/financial_analyst/output` to `/workspace/output` (read-write output sync destination).
3.  **Sandbox Execution**: The agent uses Google Search to fetch stock news, queries live Yahoo Finance stock prices, and writes the output PDF directly to `/workspace/output/financial_report.pdf` using GCS Fuse.
4.  **Automatic Client Sync**: The prober script detects the GCS mount configuration in `agent.yaml`, waits for the file to finalize, and downloads it locally from Google Cloud Storage.

---

## How to Run

Ensure you have completed the main [setup](file:///Users/zhaofu/workspace/interactions_api/showcase/README.md#setup) first.

Run the prober from the `showcase` directory:
```bash
./venv/bin/python3 showcase/prober.py showcase/financial_analyst
```

Upon success, the script will automatically download the generated PDF report and save it to `showcase/financial_analyst/output/financial_report.pdf`.
