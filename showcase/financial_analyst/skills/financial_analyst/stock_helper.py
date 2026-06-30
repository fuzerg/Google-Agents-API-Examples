import urllib.request
import json

def get_stock_data(ticker: str) -> dict:
    """Fetches real-time stock data from Yahoo Finance chart API.
    Returns a dictionary with price, previous close, currency, and exchange.
    """
    try:
        ticker = ticker.strip().upper()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        
        # User-Agent header is required by Yahoo Finance to prevent HTTP 401/403
        req = urllib.request.Request(
            url, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if not data.get("chart") or not data["chart"].get("result"):
                return {"error": f"No data found for ticker {ticker}"}
                
            result = data['chart']['result'][0]
            meta = result['meta']
            
            return {
                "ticker": ticker,
                "price": meta.get("regularMarketPrice"),
                "previous_close": meta.get("previousClose"),
                "currency": meta.get("currency"),
                "exchange": meta.get("exchangeName")
            }
    except Exception as e:
        return {"error": f"Failed to fetch data for {ticker}: {str(e)}"}
