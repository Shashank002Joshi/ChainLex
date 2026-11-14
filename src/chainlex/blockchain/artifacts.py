"""ABI and bytecode artifacts for SettlementHub smart contract."""

from typing import Any

SETTLEMENT_HUB_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {
        "inputs": [],
        "name": "InvalidSettlementId",
        "type": "error",
    },
    {
        "inputs": [],
        "name": "SettlementAlreadyFrozen",
        "type": "error",
    },
    {
        "inputs": [],
        "name": "Unauthorized",
        "type": "error",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "settlementId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amountMinor", "type": "uint256"},
            {"indexed": False, "internalType": "string", "name": "currency", "type": "string"},
        ],
        "name": "SettlementInitiated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "settlementId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "counterparty", "type": "address"},
            {"indexed": False, "internalType": "string", "name": "reason", "type": "string"},
            {"indexed": True, "internalType": "address", "name": "operator", "type": "address"},
        ],
        "name": "SettlementFrozen",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "merkleRoot", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "batchCount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "AuditRootPinned",
        "type": "event",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "settlementId", "type": "bytes32"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amountMinor", "type": "uint256"},
            {"internalType": "string", "name": "currency", "type": "string"},
        ],
        "name": "initiateSettlement",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "settlementId", "type": "bytes32"},
            {"internalType": "address", "name": "counterparty", "type": "address"},
            {"internalType": "string", "name": "reason", "type": "string"},
        ],
        "name": "freezeSettlement",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "settlementId", "type": "bytes32"}],
        "name": "isSettlementHeld",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "root", "type": "bytes32"},
            {"internalType": "uint256", "name": "batchCount", "type": "uint256"},
        ],
        "name": "pinAuditRoot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getAuditRootCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "operator",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

TOPIC_SETTLEMENT_INITIATED = "0x676662d26f44cac97a9adaaacd070d76939d9b0e3cae099e99165ff694a20539"
TOPIC_SETTLEMENT_FROZEN = "0x895c23d9d6c477b4e6107f27719bc987e6199ae8f1db3780923d7cb978a303d5"
TOPIC_AUDIT_ROOT_PINNED = "0x630645a822292e0c735a4d9ccab1ccdfd4b257177b7cfb5e5dd522b9e91c695a"
