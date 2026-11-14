"""Validated corpus loading shared by database seeding and explicit ingestion."""

import json
from importlib.resources import files
from pathlib import Path

from chainlex.domain.routing import BankAdmissionPolicy
from chainlex.services.country_rules import Regulation, ReviewPolicy


def default_corpus_directory() -> Path:
    bundled = Path(str(files("chainlex").joinpath("data/country_rules")))
    if bundled.is_dir():
        return bundled
    source = Path(__file__).resolve().parents[3] / "data" / "country_rules"
    if source.is_dir():
        return source
    raise ValueError("Country corpus is unavailable; reinstall the package with bundled seed data")


def load_corpus(directory: Path | None = None, *, regulations_only: bool = False):
    directory = directory if directory is not None else default_corpus_directory()
    rules = [
        Regulation.model_validate(r)
        for r in json.loads((directory / "regulations.json").read_text())
    ]
    policies = (
        []
        if regulations_only
        else [
            ReviewPolicy.model_validate(p)
            for p in json.loads((directory / "policies.json").read_text())
        ]
    )
    ids = {r.rule_id for r in rules}
    if len(ids) != len(rules) or len({p.policy_id for p in policies}) != len(policies):
        raise ValueError("Duplicate rule or policy ID")
    for policy in policies:
        if not policy.source_rule_ids or not set(policy.source_rule_ids) <= ids:
            raise ValueError("Policy references missing source rules")
        if any(
            r.jurisdiction != policy.jurisdiction
            for r in rules
            if r.rule_id in policy.source_rule_ids
        ):
            raise ValueError("Policy/source jurisdiction mismatch")
    return rules, policies


def load_bank_corpus(directory: Path | None = None) -> list[BankAdmissionPolicy]:
    directory = directory if directory is not None else default_corpus_directory()
    path = directory / "bank_policies.json"
    if not path.exists():
        return []
    policies = [BankAdmissionPolicy.model_validate(p) for p in json.loads(path.read_text())]
    keys = [(p.tenant_id, p.bank_id, p.version) for p in policies]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate bank policy version")
    return policies
