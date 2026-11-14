"""Semantic blockchain transaction explorer combining Voyage AI and Atlas Vector Search."""

from typing import Any

from chainlex.domain.settlement import RoutedSettlement
from chainlex.services.embeddings import (
    VoyageEmbeddings,
    embedding_metadata,
    has_current_embedding,
    validate_vector,
)


def format_tx_narrative(tx: dict[str, Any]) -> str:
    """Formats raw transaction fields into an interpretable financial narrative."""
    if tx.get("settlements"):
        narratives = []
        for payload in tx["settlements"]:
            settlement = RoutedSettlement.model_validate(
                {
                    key: value
                    for key, value in payload.items()
                    if key in RoutedSettlement.model_fields
                }
            )
            narratives.append(
                f"Settlement request {settlement.settlement_id}: "
                f"{settlement.asset.display_amount()} {settlement.asset.symbol}, "
                f"initiator wallet {settlement.initiator_wallet}, beneficiary wallet "
                f"{settlement.beneficiary_wallet}. Submitted route: "
                f"{settlement.route.narrative()}. Institution claims are UNVERIFIED; "
                "this event does not establish compliance approval or payment finality."
            )
        return " ".join(narratives)
    from_addr = tx.get("from", "unknown")
    to_addr = tx.get("to", "unknown")
    whole, cents = divmod(tx.get("value_minor", 0), 100)
    currency = tx.get("currency", "USD")
    block = tx.get("block_number", "pending")
    status = "SUCCESS" if tx.get("status", 1) == 1 else "FAILED"

    narrative = (
        f"On-chain settlement of {whole}.{cents:02d} {currency} from {from_addr} to {to_addr} "
        f"at block height {block} with execution status {status}."
    )
    if "memo" in tx:
        narrative += f" Narrative memo: {tx['memo']}."
    return narrative


class TransactionVectorizer:
    """Vectorizes on-chain transactions and executes tenant-scoped Atlas Vector Search."""

    def __init__(
        self, db: Any, voyage_client: VoyageEmbeddings | None = None, tenant_id: str = "bank_a"
    ):
        self.db = db
        self.voyage = voyage_client
        self.tenant_id = tenant_id

    async def vectorize_transaction(
        self, tx_hash: str, custom_vector: list[float] | None = None
    ) -> list[float] | None:
        """Embeds a stored transaction narrative and saves to chain_transactions.embedding."""
        tx = await self.db.chain_transactions.find_one(
            {"tenant_id": self.tenant_id, "tx_hash": tx_hash}
        )
        if not tx:
            return None

        narrative = format_tx_narrative(tx)

        if custom_vector is not None:
            validate_vector(custom_vector)
            embedding = custom_vector
        elif has_current_embedding(tx, narrative):
            return tx["embedding"]
        elif self.voyage is not None:
            embedding = (await self.voyage.embed([narrative], "document"))[0]
        else:
            return None

        await self.db.chain_transactions.update_one(
            {"tenant_id": self.tenant_id, "tx_hash": tx_hash},
            {
                "$set": {
                    "embedding": embedding,
                    "narrative": narrative,
                    **embedding_metadata(narrative),
                }
            },
        )
        return embedding

    def build_vector_search_pipeline(
        self,
        query_vector: list[float],
        limit: int = 10,
        num_candidates: int = 50,
    ) -> list[dict[str, Any]]:
        """Constructs an Atlas $vectorSearch pipeline scoped strictly by tenant."""
        validate_vector(query_vector)
        return [
            {
                "$vectorSearch": {
                    "index": "chain_transactions_idx",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": num_candidates,
                    "limit": limit,
                    "filter": {
                        "$and": [
                            {"tenant_id": {"$eq": self.tenant_id}},
                            {"is_canonical": {"$eq": True}},
                            {"is_orphaned": {"$eq": False}},
                        ]
                    },
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "tx_hash": 1,
                    "from": 1,
                    "to": 1,
                    "value_minor": 1,
                    "block_number": 1,
                    "narrative": 1,
                    "settlements": 1,
                    "chain_id": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
