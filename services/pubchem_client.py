# SPDX-License-Identifier: LGPL-3.0-or-later
import requests

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
REQUEST_TIMEOUT = (5, 60)


def fetch_aids_for_protein(protein):
    url = f"{BASE_URL}/assay/target/accession/{protein}/aids/JSON"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_cids_for_aid_batch(batch):
    url = (
        f"{BASE_URL}/assay/aid/"
        f"{','.join(map(str, batch))}/cids/JSON"
    )
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_compound_titles_for_cid_batch(batch):
    url = (
        f"{BASE_URL}/compound/cid/"
        f"{','.join(map(str, batch))}/property/Title/JSON"
    )
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_assay_activity_csv(aid):
    url = f"{BASE_URL}/assay/aid/{aid}/CSV"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text
