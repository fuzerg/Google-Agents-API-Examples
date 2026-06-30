# Financial Analyst Skill: Yahoo Finance & PDF Generation

You have access to two custom Python helper modules located in your workspace at `/workspace/skills/financial_analyst/`:
1.  `stock_helper.py`: Exposes `get_stock_data(ticker)` which returns a dictionary of real-time stock metrics (price, previous close, exchange, currency) from Yahoo Finance.
2.  `pdf_helper.py`: Exposes `generate_pdf_report(filename, report_data)` which generates a beautiful, formatted PDF report and saves it to the specified filename.

### How to use these helpers:
1.  Write a Python script that imports them.
2.  You **must** add the skill directory to your Python path before importing:
    ```python
    import sys
    sys.path.append('/workspace/skills/financial_analyst')
    import stock_helper
    import pdf_helper
    ```
3.  Execute your script using your `code_execution` tool to fetch the stock data and write the PDF report (e.g., saving it to `/workspace/report.pdf`).
4.  Once the PDF is successfully generated, read the PDF file, encode it in **base64**, and print it to stdout wrapped in `__PDF_START__` and `__PDF_END__` markers. This allows the client script to extract and save the PDF locally:
    ```python
    import base64
    with open("/workspace/report.pdf", "rb") as f:
        print("__PDF_START__")
        print(base64.b64encode(f.read()).decode())
        print("__PDF_END__")
    ```

### Example Python Script to Run in Sandbox:
```python
import sys
sys.path.append('/workspace/skills/financial_analyst')
import stock_helper
import pdf_helper
import base64

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

# 3. Generate PDF
pdf_helper.generate_pdf_report("/workspace/report.pdf", report_data)

# 4. Stream PDF back as base64
with open("/workspace/report.pdf", "rb") as f:
    print("__PDF_START__")
    print(base64.b64encode(f.read()).decode())
    print("__PDF_END__")
```

Always follow this pattern to fetch Yahoo Finance data and return the final report as a PDF.
