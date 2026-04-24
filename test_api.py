import requests

url = "http://localhost:8000/api/screener"
params = {
    "universe": "NASDAQ100",
    "sort_by": "vol_ratio",
    "sort_order": "desc"
}
# Add headers if needed
headers = {"X-API-Key": "institutional-secret-key"}

try:
    response = requests.get(url, params=params, headers=headers)
    print("Status:", response.status_code)
    print("Results count:", len(response.json().get("results", [])))
    if response.status_code != 200:
        print("Error:", response.text)
except Exception as e:
    print("Error:", e)
