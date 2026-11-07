import json

import responses

from jobradar.ingest.discover import ASHBY_URL, GREENHOUSE_URL, discover, token_candidates
from jobradar.ingest.http import PoliteClient


def test_token_candidates_from_legal_names():
    assert token_candidates("DoorDash, Inc.") == ["doordash"]
    assert token_candidates("Palantir Technologies Inc.") == [
        "palantirtechnologies",
        "palantir",
        "palantir-technologies",
    ]
    assert token_candidates("Duolingo, Inc.")[0] == "duolingo"
    assert token_candidates("") == []


@responses.activate
def test_discover_reports_hits_with_board_company_name():
    def board(token, source, jobs):
        url = (GREENHOUSE_URL if source == "greenhouse" else ASHBY_URL).format(token=token)
        responses.get(url, body=json.dumps({"jobs": jobs}), status=200 if jobs else 404)

    board("doordash", "greenhouse", [{"title": "Data Analyst", "company_name": "DoorDash"}])
    board("doordash", "ashby", [])
    board("waymo", "greenhouse", [])
    board("waymo", "ashby", [{"title": "ML Engineer"}])

    client = PoliteClient(1000, 5, 0, "test")
    hits = discover(client, ["DoorDash, Inc.", "Waymo LLC", "DOORDASH INC"])

    assert [(h.employer_name, h.source, h.token, h.jobs) for h in hits] == [
        ("DoorDash, Inc.", "greenhouse", "doordash", 1),
        ("Waymo LLC", "ashby", "waymo", 1),
        ("DOORDASH INC", "greenhouse", "doordash", 1),  # cached: no second request
    ]
    assert hits[0].board_company_name == "DoorDash"
    assert len(responses.calls) == 4


@responses.activate
def test_known_token_is_tried_first():
    responses.get(
        GREENHOUSE_URL.format(token="doordashusa"),
        body=json.dumps({"jobs": [{"title": "Analyst", "company_name": "DoorDash USA"}]}),
    )
    responses.get(ASHBY_URL.format(token="doordashusa"), status=404, body="{}")

    client = PoliteClient(1000, 5, 0, "test")
    hits = discover(client, ["DoorDash, Inc."], {"DoorDash, Inc.": "doordashusa"})

    assert [(h.token, h.board_company_name) for h in hits] == [("doordashusa", "DoorDash USA")]
    assert len(responses.calls) == 2  # the guessed "doordash" was never needed
