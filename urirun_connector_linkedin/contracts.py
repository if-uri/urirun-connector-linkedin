# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Route contracts for the LinkedIn connector.

The connector implementation talks to LinkedIn's official API. These declarations pin the
wire-level input/output shapes that the planner and CI can rely on; they do not make the
publish route reversible, because this connector has no safe general-purpose delete/undo route.
"""
from __future__ import annotations

from urirun_connectors_toolkit.contract_gate import Contract

_HEAD = {"ok": "const:true", "connector": "const:linkedin"}


CONTRACTS: dict[str, Contract] = {
    "profile/query/read": Contract(
        version="v2",  # v1 read /v2/me (r_liteprofile, retired); v2 reads OIDC /v2/userinfo
        effect="query",
        inp={"token": "?str", "secret_allow": "?str"},
        out={
            **_HEAD,
            "action": "const:profile_read",
            "member_urn": "str",
            "first_name": "str",
            "last_name": "str",
            "full_name": "str",
            "email": "str",
            "raw": "obj",
        },
        errors=("unauthenticated", "unreachable"),
        examples=(
            {
                "payload": {"token": "tok-123"},
                "result": {
                    "ok": True,
                    "connector": "linkedin",
                    "action": "profile_read",
                    "member_urn": "urn:li:person:abc123XYZ",
                    "first_name": "Tom",
                    "last_name": "Sapletta",
                    "full_name": "Tom Sapletta",
                    "email": "tom@example.com",
                    "raw": {
                        "sub": "abc123XYZ",
                        "given_name": "Tom",
                        "family_name": "Sapletta",
                        "name": "Tom Sapletta",
                        "email": "tom@example.com",
                    },
                },
            },
        ),
    ),
    "post/command/publish": Contract(
        version="v2",  # v1 posted /v2/ugcPosts (retired); v2 posts /rest/posts (Posts API)
        effect="command",
        reversible=False,
        inp={
            "text": "str",
            "token": "?str",
            "person_urn": "?str",
            "visibility": "?enum:PUBLIC|CONNECTIONS",
            "secret_allow": "?str",
        },
        out={
            **_HEAD,
            "action": "const:post_publish",
            "published": "const:true",
            "post_urn": "str",
            "author": "str",
            "visibility": "enum:PUBLIC|CONNECTIONS",
            "length": "int",
        },
        errors=("precondition-unmet", "unauthenticated", "unreachable"),
        examples=(
            {
                "payload": {
                    "text": "Shipping a thing today.",
                    "token": "tok-abc",
                    "person_urn": "urn:li:person:ABC",
                    "visibility": "PUBLIC",
                },
                "result": {
                    "ok": True,
                    "connector": "linkedin",
                    "action": "post_publish",
                    "published": True,
                    "post_urn": "urn:li:ugcPost:7",
                    "author": "urn:li:person:ABC",
                    "visibility": "PUBLIC",
                    "length": 23,
                },
            },
        ),
    ),
    "post/command/draft": Contract(
        version="v1",
        effect="command",
        reversible=False,  # pure local preview — nothing external to undo
        inp={"text": "str", "visibility": "?enum:PUBLIC|CONNECTIONS"},
        out={
            **_HEAD,
            "action": "const:post_draft",
            "published": "const:false",
            "visibility": "enum:PUBLIC|CONNECTIONS",
            "length": "int",
            "remaining": "int",
            "over_limit": "bool",
            "hashtags": ["str"],
            "preview": "str",
        },
        errors=("precondition-unmet",),
        examples=(
            {
                "payload": {"text": "Shipping #ifuri today. #mcp", "visibility": "PUBLIC"},
                "result": {
                    "ok": True,
                    "connector": "linkedin",
                    "action": "post_draft",
                    "published": False,
                    "visibility": "PUBLIC",
                    "length": 27,
                    "remaining": 2973,
                    "over_limit": False,
                    "hashtags": ["#ifuri", "#mcp"],
                    "preview": "Shipping #ifuri today. #mcp",
                },
            },
        ),
    ),
    "post/query/list": Contract(
        version="v2",  # v1 read /v2/ugcPosts?q=authors (retired); v2 reads /rest/posts?q=author
        effect="query",
        inp={"token": "?str", "person_urn": "?str", "count": "?int", "secret_allow": "?str"},
        out={
            **_HEAD,
            "action": "const:post_list",
            "count": "int",
            "posts": [
                {
                    "urn": "str",
                    "text": "str",
                    "lifecycleState": "str",
                    "created": "int",
                }
            ],
            "author": "str",
        },
        errors=("unauthenticated", "unreachable"),
        examples=(
            {
                "payload": {
                    "token": "tok-abc",
                    "person_urn": "urn:li:person:ABC",
                    "count": 2,
                },
                "result": {
                    "ok": True,
                    "connector": "linkedin",
                    "action": "post_list",
                    "count": 2,
                    "posts": [
                        {
                            "urn": "urn:li:share:1",
                            "text": "post A",
                            "lifecycleState": "PUBLISHED",
                            "created": 1750672800000,
                        },
                        {
                            "urn": "urn:li:share:2",
                            "text": "post B",
                            "lifecycleState": "PUBLISHED",
                            "created": 1750669200000,
                        },
                    ],
                    "author": "urn:li:person:ABC",
                },
            },
        ),
    ),
}
