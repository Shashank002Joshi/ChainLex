"""Versioned settlement event payloads; institution claims require off-chain verification."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from chainlex.domain.models import Contract
from chainlex.domain.routing import SettlementRoute

EVMAddress = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$")]
Bytes32 = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{64}$")]


class SettlementAsset(Contract):
    # String preserves all uint256 values in MongoDB/JSON without int64 overflow.
    amount_atomic: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,77}$")]
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{2,12}$")]
    decimals: Annotated[int, Field(strict=True, ge=0, le=18)]
    contract_address: EVMAddress

    @field_validator("amount_atomic")
    @classmethod
    def uint256_amount(cls, value):
        if int(value) >= 2**256:
            raise ValueError("Amount exceeds uint256")
        return value

    @field_validator("contract_address")
    @classmethod
    def normalized_address(cls, value):
        return value.lower()

    def display_amount(self) -> str:
        divisor = 10**self.decimals
        whole, remainder = divmod(int(self.amount_atomic), divisor)
        if not self.decimals:
            return str(whole)
        return f"{whole}.{remainder:0{self.decimals}d}"


class RoutedSettlement(Contract):
    event_version: Literal[2] = 2
    settlement_id: Bytes32
    initiator_wallet: EVMAddress
    beneficiary_wallet: EVMAddress
    asset: SettlementAsset
    route: SettlementRoute
    instructions_hash: Bytes32
    institution_verification: Literal["UNVERIFIED"] = "UNVERIFIED"

    @field_validator("initiator_wallet", "beneficiary_wallet", "settlement_id", "instructions_hash")
    @classmethod
    def normalized_hex(cls, value):
        return value.lower()

    @field_validator("settlement_id", "initiator_wallet", "beneficiary_wallet", "instructions_hash")
    @classmethod
    def nonzero_identity(cls, value):
        if int(value, 16) == 0:
            raise ValueError(
                "Settlement ID, participant wallets, and instructions hash must be nonzero"
            )
        return value

    @model_validator(mode="after")
    def distinct_participants(self):
        if self.initiator_wallet.lower() == self.beneficiary_wallet.lower():
            raise ValueError(
                "Self-settlement prohibited: initiator and beneficiary wallets cannot be identical"
            )
        return self
