"""
Fetching the data and look at it

"""

import requests

url = "https://cricketsasa.ca/cricket/comm_4_res.php"
params = {
     "match_id": "208",
    "year": "2026",
    "batting_team_id": "174",
    "bowling_team_id": "1213",
    "total_overs": "50",
    "comm_option": "1",
}

response = requests.get(url, params=params, verify= False, timeout=15)
print("Status code :" , response.status_code)
print("Length of response:" ,len(response.text))
print("\n--- First 500 characters of the response ---")
print(response.text[:500])