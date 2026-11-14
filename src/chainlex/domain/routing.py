"""Ordered settlement routes and bank-owned originator admission controls."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from chainlex.domain.models import Contract, Identifier

Country = Literal["SG", "CA", "US"]


class WalletIdentity(Contract):
    network: Identifier
    address: Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$")]

    @field_validator("network")
    @classmethod
    def canonical_network(cls, value: str) -> str:
        if value != value.strip() or value != value.lower():
            raise ValueError("Use a canonical lowercase network identifier")
        return value

    @field_validator("address")
    @classmethod
    def canonical_address(cls, value: str) -> str:
        return value.lower()


class RouteBank(Contract):
    bank_id: Identifier
    jurisdiction: Country


class SettlementRoute(Contract):
    route_id: Identifier
    banks: Annotated[tuple[RouteBank, ...], Field(min_length=2, max_length=32)]

    @model_validator(mode="after")
    def distinct_banks(self):
        ids = [bank.bank_id for bank in self.banks]
        if len(ids) != len(set(ids)):
            raise ValueError("Repeated banks create a routing loop")
        return self

    @property
    def jurisdictions(self) -> tuple[Country, ...]:
        return tuple(dict.fromkeys(bank.jurisdiction for bank in self.banks))

    def narrative(self) -> str:
        return " -> ".join(f"{bank.bank_id} ({bank.jurisdiction})" for bank in self.banks)


class AllowlistEntry(Contract):
    wallet: WalletIdentity
    label: str = ""


class BankAdmissionPolicy(Contract):
    policy_id: Identifier
    tenant_id: Identifier
    bank_id: Identifier
    version: Annotated[int, Field(strict=True, ge=1)]
    policy_type: Literal["BANK_ORIGINATOR_ALLOWLIST"] = "BANK_ORIGINATOR_ALLOWLIST"
    # Originator admission normally belongs to the originating bank. A receiving
    # bank may explicitly require the original sender to be on its own list too.
    scope: Literal["ORIGINATING_BANK", "ALL_ROUTE_POSITIONS"] = "ORIGINATING_BANK"
    allowed_originators: tuple[AllowlistEntry, ...] = ()
    is_active: bool = False
    review_status: Literal["UNVERIFIED", "VERIFIED"] = "UNVERIFIED"
