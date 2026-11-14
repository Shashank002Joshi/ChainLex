// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title SettlementHub
 * @notice Enterprise settlement escrow and compliance coordination hub.
 * Supports settlement lifecycle events, automated protective freezing, and Merkle audit root pinning.
 */
contract SettlementHub {
    address public operator;

    // Settlement state: settlementId => isHeld
    mapping(bytes32 => bool) public isSettlementHeld;
    mapping(bytes32 => address) public settlementCounterparty;
    mapping(bytes32 => string) public freezeReason;

    // Merkle root audit anchors: root => batchCount
    mapping(bytes32 => uint256) public auditRootBatches;
    bytes32[] public allAuditRoots;

    struct SettlementDetails {
        uint256 amountAtomic;
        string assetSymbol;
        uint8 assetDecimals;
        address assetContract;
        string routeId;
        string[] institutionIds;
        string[] countryCodes;
        bytes32 instructionsHash;
    }

    mapping(bytes32 => bool) public routedSettlementExists;

    // V2 is additive: existing SettlementInitiated consumers remain compatible.
    // Institution IDs and countries are submitted claims, not bank attestations.
    event SettlementInitiatedV2(
        bytes32 indexed settlementId,
        address indexed initiator,
        address indexed beneficiary,
        SettlementDetails details
    );

    event SettlementInitiated(
        bytes32 indexed settlementId,
        address indexed from,
        address indexed to,
        uint256 amountMinor,
        string currency
    );

    event SettlementFrozen(
        bytes32 indexed settlementId,
        address indexed counterparty,
        string reason,
        address indexed operator
    );

    event AuditRootPinned(
        bytes32 indexed merkleRoot,
        uint256 batchCount,
        uint256 timestamp
    );

    error Unauthorized();
    error SettlementAlreadyFrozen();
    error InvalidSettlementId();

    modifier onlyOperator() {
        if (msg.sender != operator) revert Unauthorized();
        _;
    }

    constructor() {
        operator = msg.sender;
    }

    function transferOperator(address newOperator) external onlyOperator {
        require(newOperator != address(0), "Invalid operator");
        operator = newOperator;
    }

    /**
     * @notice Initiates a settlement for tracking and indexer ingestion.
     */
    function initiateSettlement(
        bytes32 settlementId,
        address to,
        uint256 amountMinor,
        string calldata currency
    ) external {
        if (settlementId == bytes32(0)) revert InvalidSettlementId();
        settlementCounterparty[settlementId] = to;
        emit SettlementInitiated(settlementId, msg.sender, to, amountMinor, currency);
    }

    /**
     * @notice Records a routed settlement request, not a completed token transfer.
     * @dev Private customer/Travel Rule data stays off-chain; only its hash is emitted.
     * Admission and institution ownership are checked by the off-chain policy gate.
     */
    function initiateRoutedSettlement(
        bytes32 settlementId,
        address beneficiary,
        SettlementDetails calldata details
    ) external {
        if (settlementId == bytes32(0)) revert InvalidSettlementId();
        require(!routedSettlementExists[settlementId], "Duplicate settlement");
        require(beneficiary != address(0), "Missing beneficiary");
        require(details.amountAtomic > 0, "Amount must be positive");
        require(details.assetDecimals <= 18, "Unsupported decimals");
        bytes memory symbol = bytes(details.assetSymbol);
        require(symbol.length >= 2 && symbol.length <= 12, "Invalid asset symbol");
        for (uint256 i = 0; i < symbol.length; i++) {
            require((symbol[i] >= 0x41 && symbol[i] <= 0x5a) ||
                    (symbol[i] >= 0x30 && symbol[i] <= 0x39), "Invalid asset symbol");
        }
        require(bytes(details.routeId).length > 0 && bytes(details.routeId).length <= 128,
                "Invalid route ID");
        uint256 count = details.institutionIds.length;
        require(count >= 2 && count <= 32 && details.countryCodes.length == count,
                "Invalid route length");
        for (uint256 i = 0; i < count; i++) {
            require(bytes(details.institutionIds[i]).length > 0 &&
                    bytes(details.institutionIds[i]).length <= 128, "Invalid institution ID");
            bytes32 country = keccak256(bytes(details.countryCodes[i]));
            require(country == keccak256("CA") || country == keccak256("US") ||
                    country == keccak256("SG"), "Unsupported country");
            for (uint256 j = 0; j < i; j++) {
                require(keccak256(bytes(details.institutionIds[i])) !=
                        keccak256(bytes(details.institutionIds[j])), "Routing loop");
            }
        }
        routedSettlementExists[settlementId] = true;
        settlementCounterparty[settlementId] = beneficiary;
        emit SettlementInitiatedV2(settlementId, msg.sender, beneficiary, details);
    }

    /**
     * @notice Freezes a settlement following an auditable compliance policy decision.
     */
    function freezeSettlement(
        bytes32 settlementId,
        address counterparty,
        string calldata reason
    ) external onlyOperator {
        if (settlementId == bytes32(0)) revert InvalidSettlementId();
        if (isSettlementHeld[settlementId]) revert SettlementAlreadyFrozen();

        isSettlementHeld[settlementId] = true;
        settlementCounterparty[settlementId] = counterparty;
        freezeReason[settlementId] = reason;

        emit SettlementFrozen(settlementId, counterparty, reason, msg.sender);
    }

    /**
     * @notice Pins a cryptographic Merkle root of MongoDB Atlas audit records.
     */
    function pinAuditRoot(bytes32 root, uint256 batchCount) external onlyOperator {
        auditRootBatches[root] = batchCount;
        allAuditRoots.push(root);
        emit AuditRootPinned(root, batchCount, block.timestamp);
    }

    function getAuditRootCount() external view returns (uint256) {
        return allAuditRoots.length;
    }
}
