# Financial Analyst Skill: Yahoo Finance & PDF Generation

You have access to two custom Python helper modules located in your workspace at `/.agents/skills/financial_analyst/scripts/`:
1.  `stock_helper.py`: Exposes `get_stock_data(ticker)` which returns a dictionary of real-time stock metrics (price, previous close, exchange, currency) from Yahoo Finance.
2.  `pdf_helper.py`: Exposes `generate_pdf_report(filename, report_data)` which generates a beautiful, formatted PDF report and saves it to the specified filename.

### How to use these helpers:
1.  Write a Python script that imports them.
2.  You **must** add the skill scripts directory to your Python path before importing:
    ```python
    import sys
    sys.path.append('/.agents/skills/financial_analyst/scripts')
    import stock_helper
    import pdf_helper
    ```
3.  Execute your script using your `code_execution` tool to fetch the stock data and write the PDF report, saving it to the output path specified by your system instructions (e.g. `/workspace/output/financial_report.pdf`).
4.  You **do not** need to encode the PDF to base64 or print it to stdout. The output directory is a GCS Fuse mount, and any files saved there are automatically synced to the cloud.

### Example Python Script to Run in Sandbox:
```python
import os
import sys
sys.path.append('/.agents/skills/financial_analyst/scripts')
import stock_helper
import pdf_helper

# 1. Fetch stock data
goog_data = stock_helper.get_stock_data("GOOG")
msft_data = stock_helper.get_stock_data("MSFT")

# 2. Structure data for the PDF
report_data = {
    "tickers": ["GOOG", "MSFT"],
    "current_prices": {
        "GOOG": f"${goog_data.get('price')} {goog_data.get('currency')}",
        "MSFT": f"${msft_data.get('price')} {msft_data.get('currency')}"
    },
    "summary": "...", # Your detailed news analysis
    "sentiment": "...", # Your overall sentiment
    "recommendation": "..." # Your detailed buy/sell recommendation
}

# 3. Determine the output path from your instructions (e.g. /workspace/output/financial_report.pdf)
output_path = "/workspace/output/financial_report.pdf"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

# 4. Generate PDF report directly to the output GCS mount
pdf_helper.generate_pdf_report(output_path, report_data)
print(f"PDF report successfully saved to {output_path}")
```

Always follow this pattern to fetch Yahoo Finance data and write the final report directly to the target output path.
