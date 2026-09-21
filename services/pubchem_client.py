# SPDX-License-Identifier: LGPL-3.0-or-later
import requests

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
REQUEST_TIMEOUT = (5, 60)
ASSAY_SID_PAGE_SIZE = 10000


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
    url = f"{BASE_URL}/compound/cid/property/Title/JSON"
    response = requests.post(
        url,
        data={"cid": ",".join(map(str, batch))},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_assay_activity_csv(aid):
    url = f"{BASE_URL}/assay/aid/{aid}/CSV"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def fetch_assay_sid_listkey(aid):
    url = f"{BASE_URL}/assay/aid/{aid}/sids/JSON"
    response = requests.get(
        url,
        params={"list_return": "listkey"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    identifiers = response.json().get("IdentifierList", {})
    listkey = identifiers.get("ListKey")
    size = identifiers.get("Size")

    if listkey in (None, "") or size is None:
        raise ValueError(
            f"PubChem did not return a SID ListKey for AID {aid}."
        )

    try:
        size = int(size)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"PubChem returned an invalid SID ListKey size for AID {aid}."
        ) from exc

    if size < 0:
        raise ValueError(
            f"PubChem returned a negative SID ListKey size for AID {aid}."
        )

    return {
        "listkey": str(listkey),
        "size": size,
    }


def fetch_assay_activity_csv_page(
    aid,
    listkey,
    start,
    count=ASSAY_SID_PAGE_SIZE,
):
    if start < 0:
        raise ValueError("start cannot be negative.")
    if count <= 0 or count > ASSAY_SID_PAGE_SIZE:
        raise ValueError(
            f"count must be between 1 and {ASSAY_SID_PAGE_SIZE}."
        )
    if str(listkey).strip() == "":
        raise ValueError("listkey cannot be empty.")

    url = f"{BASE_URL}/assay/aid/{aid}/CSV"
    response = requests.get(
        url,
        params={
            "sid": "listkey",
            "listkey": str(listkey),
            "listkey_start": int(start),
            "listkey_count": int(count),
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text
