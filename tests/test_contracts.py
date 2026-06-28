# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
from __future__ import annotations

import pytest

pytest.importorskip("urirun_connectors_toolkit.contract_gate")

import urirun_connector_linkedin as li  # noqa: E402
from urirun_connector_linkedin import core  # noqa: E402
from urirun_connector_linkedin.contracts import CONTRACTS  # noqa: E402
from urirun_connectors_toolkit.contract_gate import conform  # noqa: E402
from urirun_contract.contract_lint import lint_handler_signatures  # noqa: E402


ROUTE_PUBLISH = "linkedin://host/post/command/publish"


def test_contracts_conform():
    conform(CONTRACTS)


def test_contracts_match_live_handler_signatures():
    problems = lint_handler_signatures(CONTRACTS, li.urirun_bindings(), conn_uri=core.conn.uri)
    assert problems == []


def test_bindings_carry_contract_metadata():
    bindings = li.urirun_bindings()["bindings"]
    contract = bindings[ROUTE_PUBLISH]["meta"]["contract"]
    assert contract["effect"] == "command"
    assert contract["reversible"] is False
    assert contract["output"]["published"] == "const:true"
    assert contract["output"]["visibility"] == "enum:PUBLIC|CONNECTIONS"
