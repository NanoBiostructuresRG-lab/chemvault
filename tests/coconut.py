# SPDX-License-Identifier: LGPL-3.0-or-later
import requests

url = "https://coconut.naturalproducts.net/api/collections"


headers = {
    "Authorization": "Bearer 196712|LLIIPk9RfqZp6f0orX2QxrrHIpighDZgbadJhfK0bffb7c57"
}
body ={
  "search": {
    "scopes": [],
    "filters": [
    ],
    "sorts": [
      {
        "field": "title",
        "direction": "desc"
      },
      {
        "field": "description",
        "direction": "desc"
      },
      {
        "field": "identifier",
        "direction": "desc"
      },
      {
        "field": "url",
        "direction": "desc"
      }
    ],
    "selects": [
      {
        "field": "title"
      },
      {
        "field": "description"
      },
      {
        "field": "identifier"
      },
      {
        "field": "url"
      }
    ],
    "includes": [],
    "aggregates": [],
    "instructions": [],
    "gates": [
      "create",
      "update",
      "delete"
    ],
    "page": 1,
    "limit": 10
  }
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()
    print(data)
else:
    print("Error:", response.status_code)

#{'access_token': '196712|LLIIPk9RfqZp6f0orX2QxrrHIpighDZgbadJhfK0bffb7c57', 'token_type': 'Bearer'}