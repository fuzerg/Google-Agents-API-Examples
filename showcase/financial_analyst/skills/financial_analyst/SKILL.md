---
name: Financial Analyst Skill
description: Guides the agent on how to fetch historical stock data and creatively generate PDF reports with charts.
---

# Financial Analyst Skill: Advanced Stock Analysis & PDF Generation

You are tasked with generating comprehensive, creative, and visually appealing financial analysis PDF reports.

### Fetching Stock Data
You should use the `yfinance` Python library (which is available in your sandbox) to fetch historical stock data. This allows you to gather enough data points (e.g., past 1-6 months of daily closing prices, volume, etc.) to perform deep trend analysis and create charts.

```python
import yfinance as yf

# Example: Fetching historical data for analysis and charting
goog_data = yf.Ticker("GOOG").history(period="3mo")
# Use goog_data (a pandas DataFrame) to calculate moving averages, trends, etc.
```

### PDF Generation & Creativity
You have full creative freedom to design the PDF report. Use libraries like `matplotlib` to generate insightful charts (e.g., price trends, volume bars) and save them as images, then use a PDF library like `fpdf`, `reportlab`, or `matplotlib.backends.backend_pdf.PdfPages` to compile a beautiful, multi-page PDF report. 

If a library like `fpdf` or `reportlab` is not installed in the sandbox, you can install it dynamically at the start of your script using `subprocess`, or just use `matplotlib` to generate a multi-page PDF.

```python
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

output_path = "/workspace/output/financial_report.pdf"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

# Example using Matplotlib to create a creative PDF
with PdfPages(output_path) as pdf:
    # Page 1: Title and Summary text
    fig = plt.figure(figsize=(8, 11))
    plt.axis('off')
    plt.text(0.5, 0.9, 'Financial Analysis Report', ha='center', va='center', fontsize=24)
    plt.text(0.1, 0.7, 'Your creative analysis here...', fontsize=12)
    pdf.savefig(fig)
    plt.close()
    
    # Page 2: Historical Price Chart
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(goog_data.index, goog_data['Close'], label='GOOG Close Price')
    ax.set_title('GOOG 3-Month Price Trend')
    ax.legend()
    pdf.savefig(fig)
    plt.close()

print(f"PDF report successfully saved to {output_path}")
```

### Critical Rules
1. **Be Creative**: Your PDF should not be just a wall of text. Include charts, formatted text, summary metrics, and a polished layout.
2. **Deep Analysis**: Base your analysis on multiple data points over time, not just the current price.
