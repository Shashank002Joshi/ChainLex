"""Fictional fixtures, never evidence of a real bank relationship or legal clearance."""

from copy import deepcopy

from chainlex.audit.models import UnsupportedSchema

SCENARIOS = {
    "corridor_audit": "Compare fictional Canada-to-Singapore settlement corridors.",
    "memory_influence": "A prior intermediary documentation issue adds a human gate.",
    "no_suitable_route": "Both fictional corridors fail bank originator admission.",
    "schema_change": "A known source schema changes from banks to institutions.",
    "unsupported_schema": "An unknown source schema requires operator correction.",
}

SOURCES = [
    {
        "source_id": "ca-aml",
        "jurisdiction": "CA",
        "title": "FINTRAC guidance overview",
        "url": "https://fintrac-canafe.canada.ca/guidance-directives/guidance-directives-eng",
        "review_status": "UNVERIFIED",
        "provenance": "scripted_source_reference",
    },
    {
        "source_id": "us-aml",
        "jurisdiction": "US",
        "title": "FinCEN AML/CFT overview",
        "url": "https://www.fincen.gov/resources",
        "review_status": "UNVERIFIED",
        "provenance": "scripted_source_reference",
    },
    {
        "source_id": "sg-aml",
        "jurisdiction": "SG",
        "title": "MAS AML/CFT overview",
        "url": "https://www.mas.gov.sg/regulation/anti-money-laundering",
        "review_status": "UNVERIFIED",
        "provenance": "scripted_source_reference",
    },
]


def scenario_input(name: str) -> dict:
    if name not in SCENARIOS:
        raise ValueError("Unknown demo scenario")
    result = {
        "schema_version": 1,
        "description": SCENARIOS[name],
        "narrative": "Fictional USDC settlement from Canada to Singapore; assess bank "
        "admission, intermediary documentation, AML controls and source validity.",
        "asset": "USDC",
        "network": "ethereum-sepolia",
        "amount": "100000.00",
        "origin": "scotiabank",
        "destination": "dbs",
        "routes": [
            {
                "route_id": "configured-ca-us-sg",
                "provenance": "configured_demo_corridor",
                "banks": [
                    {"bank_id": "scotiabank", "jurisdiction": "CA"},
                    {"bank_id": "jpmorgan_chase", "jurisdiction": "US"},
                    {"bank_id": "dbs", "jurisdiction": "SG"},
                ],
            },
            {
                "route_id": "discovered-ca-sg",
                "provenance": "scripted_official_source_candidate",
                "connectivity_verified": False,
                "banks": [
                    {"bank_id": "scotiabank", "jurisdiction": "CA"},
                    {"bank_id": "dbs", "jurisdiction": "SG"},
                ],
            },
        ],
        "sources": deepcopy(SOURCES),
        "originator_admitted": name != "no_suitable_route",
        "fixture_version": "audit-demo-v1",
    }
    if name in {"schema_change", "unsupported_schema"}:
        result["schema_version"] = 2 if name == "schema_change" else 99
        for route in result["routes"]:
            route["institutions"] = route.pop("banks")
    return result


def adapt_context(source: dict) -> dict:
    context = deepcopy(source)
    version = context["schema_version"]
    if version not in {1, 2}:
        raise UnsupportedSchema("SOURCE_SCHEMA_NOT_SUPPORTED")
    for route in context["routes"]:
        if version == 2:
            route["banks"] = route.pop("institutions")
        if len(route["banks"]) < 2 or len({b["bank_id"] for b in route["banks"]}) != len(
            route["banks"]
        ):
            raise ValueError("Invalid corridor")
        if (route["banks"][0]["bank_id"], route["banks"][-1]["bank_id"]) != (
            context["origin"],
            context["destination"],
        ):
            raise ValueError("Corridor endpoints differ from case")
    context["adapter"] = f"reviewed-demo-source-v{version}-to-context-v1"
    context["source_schema_version"] = version
    context["schema_version"] = 1
    return context
