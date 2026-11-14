"""Semantic blockchain transaction explorer combining Voyage AI embeddings and Atlas Vector Search."""

from typing import Any


def format_tx_narrative(tx: dict[str, Any]) -> str:
    """Formats raw transaction fields into an interpretable financial/compliance narrative."""
    from_addr = tx.get("from", "unknown")
    to_addr = tx.get("to", "unknown")
    amount = tx.get("value_minor", 0) / 100.0  # e.g., cents to dollars
    currency = tx.get("currency", "USD")
    block = tx.get("block_number", "pending")
    status = "SUCCESS" if tx.get("status", 1) == 1 else "FAILED"

    narrative = (
        f"On-chain settlement of {amount:.2f} {currency} from {from_addr} to {to_addr} "
        f"at block height {block} with execution status {status}."
    )
    if "memo" in tx:
        narrative += f" Narrative memo: {tx['memo']}."
    return narrative


class TransactionVectorizer:
    """Vectorizes on-chain transactions and executes Atlas Vector Search pipelines."""

    def __init__(self, db: Any, voyage_client: Any = None, tenant_id: str = "bank_a"):
        self.db = db
        self.voyage = voyage_client
        self.tenant_id = tenant_id

    async def vectorize_transaction(self, tx_hash: str, custom_vector: list[float] | None = None) -> list[float] | None:
        """Embeds a stored transaction narrative and saves to chain_transactions.embedding."""
        tx = await self.db.chain_transactions.find_one({"tx_hash": tx_hash})
        if not tx:
            return None

        narrative = format_tx_narrative(tx)

        if custom_vector is not None:
            embedding = custom_vector
        elif self.voyage is not None:
            # Call Voyage AI voyage-finance-2 embedding API
            res = self.voyage.embed([narrative], model="voyage-finance-2")
            embedding = res.embeddings[0]
        else:
            return None

        await self.db.chain_transactions.update_one(
            {"tx_hash": tx_hash},
            {"$set": {"embedding": embedding, "narrative": narrative}},
        )
        return embedding

    def build_vector_search_pipeline(
        self,
        query_vector: list[float],
        limit: int = 10,
        num_candidates: int = 50,
    ) -> list[dict[str, Any]]:
        """Constructs an Atlas $vectorSearch pipeline scoped by tenant and canonical status."""
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
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
