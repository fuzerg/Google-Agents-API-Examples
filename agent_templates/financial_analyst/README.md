# The Smart Financial Analyst

This example demonstrates how to combine **server-side tools** (Google Search), a **custom GCS-mounted skill**, and a **GCS-mounted output path** in an autonomous background interaction. The agent uses Google Search to find live stock prices and news, analyzes them, and uses the custom `financial_analyst` skill to generate a beautiful, data-rich PDF report.

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
 │  │     - Uses yfinance for historical data        │  │
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

1.  **Provisioning & GCS Upload**: The prober script mirrors the whole local `skills/` folder to your GCS bucket (`gs://$GCS_BUCKET/financial_analyst/skills`).
2.  **Custom Agent Deployment**: The Control Plane registers the agent configuration in the cloud, specifying:
    - GCS mount `gs://$GCS_BUCKET/financial_analyst/skills` to `/.agents/skills` (read-only skill resources, so the agent sees `/.agents/skills/financial_analyst/...`).
    - GCS mount `gs://$GCS_BUCKET/financial_analyst/output/<agent_id>` to `/workspace/output` (read-write output destination, unique per agent).
3.  **Sandbox Execution**: The agent uses Google Search to fetch stock news, queries live Yahoo Finance stock prices, and writes a **uniquely named** PDF (e.g. `goog_report_<timestamp>.pdf`) to `/workspace/output/` using GCS Fuse.
4.  **Automatic Client Sync**: The prober script waits for the files to finalize, then downloads everything under the agent's output prefix locally.

---

## How to Run

Ensure you have completed the main [setup](../README.md#setup--prerequisites) first.

This template mounts a skill and an output path to Google Cloud Storage, so set
**`GCS_BUCKET`** to a bucket you own (skills are uploaded there and reports are
synced back). Export it in your shell or add it to a `.env` in this directory:
```bash
export GCS_BUCKET="your-gcs-bucket-name"
```

Run the prober from the `agent_templates` directory:
```bash
./venv/bin/python3 agent_templates/prober.py agent_templates/financial_analyst
```

Upon success, the script downloads every generated PDF report into
`agent_templates/financial_analyst/output/` (each report has a unique filename,
so multiple runs/sessions never overwrite one another).
