# ⚖️ ChainLex: Dynamic End-to-End Compliance Verification Guide

> **Official MongoDB x Voyage AI Hackathon Submission**  
> *Themes Covered: Agents You Can Audit • Memory You Can Govern • Finish The Job*

---

## 1. Executive Summary & Design Adherence

**ChainLex** is an institutional-grade, multi-agent compliance orchestration platform built to solve the fundamental safety blocker preventing autonomous AI agents from operating in enterprise finance: **agents cannot be audited before real-world execution, cannot govern their memory against statutory laws, and fail to reliably finish long-running, multi-system workflows.**

Rather than treating compliance as a static script or hardcoded mock, ChainLex provides a **Dynamic End-to-End Verification Engine** (`scripts/e2e_compliance_runner.py`) capable of ingesting **ANY** arbitrary transaction parameterization, convening a **Multi-Agent Compliance Court**, evaluating multi-jurisdiction statutory rules (FINTRAC, OFAC/FinCEN, MAS), enforcing position-scoped correspondent banking allowlists, dispatching auditable protective actions to **Ethereum Sepolia**, and computing cryptographic Merkle state anchors.

```
       ┌─────────────────────────────────────────────────────────────┐
       │                   Incoming Transaction                      │
       │   (Corridor: Scotiabank CA -> JPMorgan US -> DBS SG)        │
       └──────────────────────────────┬──────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 1: INTAKE & INVARIANT VALIDATION                           │
    │  • Anti-Wash Trading: initiator != beneficiary                  │
    │  • Non-Zero Hash: instructions_hash != 0x00...00                │
    │  • Routing Loop Prevention: no repeated corridor banks          │
    └─────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 2: IDENTITY & ROUTE ADMISSION EVALUATION                   │
    │  • BankAdmissionPolicy: ORIGINATING_BANK vs ALL_ROUTE_POSITIONS │
    │  • Originator wallet signature & network authenticity check      │
    └─────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 3: EVIDENCE & JURISDICTION DISCOVERY (Voyage AI)           │
    │  • Multi-corridor statutory aggregation: ['CA', 'US', 'SG']     │
    │  • 1024-dim voyage-finance-2 semantic search & rerank-2         │
    └─────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 4: MULTI-AGENT COMPLIANCE COURT DELIBERATION               │
    │  🔴 Agent 1 (Prosecutor): Formulates charges & citations        │
    │  🟢 Agent 2 (Defense): Argues safe harbors & mitigating proofs  │
    │  ⚖️ Agent 3 (CCO): Binding Pre-Execution Policy Gate Verdict    │
    └─────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 5: DISPATCH & PROTECTIVE EXECUTION (Ethereum Sepolia)      │
    │  • If REVIEW/DENY: Dispatches freezeSettlement(...) on-chain    │
    │  • Probe verification: receipt.status == 1, block depth,       │
    │    SettlementFrozen log, isSettlementHeld(id) == True           │
    └─────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  LEG 6: AUDIT PINNING & MERKLE ANCHORING                        │
    │  • Canonical SHA-256 document hashing of decision payload       │
    │  • Cryptographic Merkle Root state pinning to MongoDB Atlas     │
    └─────────────────────────────────────────────────────────────────┘
```

---

## 2. The Multi-Agent Compliance Court

ChainLex organizes deliberative intelligence through three specialized agent personas that review every transaction concurrently:

| Agent Persona | Role & Responsibilities | Decision Criteria |
| :--- | :--- | :--- |
| 🔴 **Regulatory Prosecutor Agent** (`ProsecutorAgent`) | Examines statutory non-compliance, missing disclosures, and corridor regulations. Formulates formal regulatory charges with exact statutory citations (e.g. MAS PSA Section 6, FATF Recommendation 16, Canadian PCMLTFA, FinCEN 31 CFR 1010.410). | Files charges when required control facts are missing or false. Advocates for `REVIEW` or immediate `DENY`. |
| 🟢 **Defense Counsel Agent** (`DefenseCounselAgent`) | Identifies regulatory safe harbors, de minimis exemptions, Tier-1 KYC verification, inter-affiliate exemptions, and institutional custody proofs. | Advocates for `APPROVE` or structured cure periods when positive mitigating facts are verified. |
| ⚖️ **Chief Compliance Officer Agent** (`ComplianceOfficerAgent`) | Authoritative judicial judge presiding over the court. Evaluates the deterministic pre-execution policy gate, weighs Prosecutor charges against Defense arguments, and issues a binding pre-execution determination. | Has zero discretionary waiver authority over sanctions or strict allowlist denials; orders automated on-chain protective holds for regulatory breaches. |

---

## 3. Dynamic Test Runner CLI: Choose ANY Transaction

The end-to-end test runner (`scripts/e2e_compliance_runner.py`) is completely dynamic. You can test any transaction using command-line arguments, JSON transaction files, or pre-configured scenario presets.

### CLI Syntax
```bash
python scripts/e2e_compliance_runner.py [OPTIONS]
```

### Core CLI Flags
| Flag | Description | Default |
| :--- | :--- | :--- |
| `--scenario` | Scenario preset: `cross_country`, `binance_hack`, `multihop_routing`, or `custom` | `custom` |
| `--origin-bank` | Originating bank identifier | `scotiabank` |
| `--origin-country` | Originating jurisdiction code (ISO-2) | `CA` |
| `--inter-bank` | Intermediary bank identifier (repeatable for multiple hops) | `jpmorgan_chase` |
| `--inter-country` | Intermediary jurisdiction code (repeatable) | `US` |
| `--dest-bank` | Destination bank identifier | `dbs` |
| `--dest-country` | Destination jurisdiction code | `SG` |
| `--amount` | Transaction value | `250000.0` |
| `--symbol` | Asset symbol (`USDC`, `USDT`, `ETH`, etc.) | `USDC` |
| `--decimals` | Asset decimal precision | `6` |
| `--initiator` | Initiator wallet address | `0x1111...1111` |
| `--beneficiary` | Beneficiary wallet address | `0x2222...2222` |
| `--instructions-hash` | 32-byte Travel Rule commitment hash | Auto-generated |
| `--no-travel-rule` | Simulate missing Travel Rule disclosure | `False` |
| `--no-cdd` | Simulate unverified Customer Due Diligence | `False` |
| `--no-sanctions-clear` | Simulate sanctions list match | `False` |
| `--no-beneficial-ownership` | Simulate unsegregated omnibus pool | `False` |
| `--wash-trade` | Force `initiator == beneficiary` | `False` |
| `--zero-instructions-hash` | Force zeroed Travel Rule hash | `False` |
| `--rogue-sender` | Use unallowlisted rogue hot wallet | `False` |
| `--strict-intermediary` | Intermediary enforces strict `ALL_ROUTE_POSITIONS` allowlist | `False` |
| `--mode` | Execution target: `simulated` (local mock) or `sepolia` (live testnet) | `simulated` |
| `--tx-file` | Ingest transaction JSON file directly | `None` |
| `--report-out` | Write complete structured JSON report to path | `None` |

---

## 4. Deep Walkthrough of the 3 Core Hackathon Scenarios

### Case 1: Cross-Country Multi-Jurisdictional Compliance (CA -> US -> SG)

**Context**: Scotiabank (Canada) initiates a $250,000.00 USDC transfer transiting JPMorgan Chase (US) to DBS Bank (Singapore), but the transaction lacks mandatory Travel Rule metadata payload.

**Command**:
```bash
python scripts/e2e_compliance_runner.py --scenario cross_country
```

**Court Execution Trace**:
1. **Leg 1 (Intake)**: Parses corridor route `scotiabank (CA) -> jpmorgan_chase (US) -> dbs (SG)`. Generates Settlement ID `0xb64075b8...`. Invariant checks pass.
2. **Leg 2 (Admission)**: Scotiabank allowlist verified for originator `0x1111...1111`. Intermediaries trust originating bank under `ORIGINATING_BANK` scope.
3. **Leg 3 (Evidence)**: Aggregates corridors `['CA', 'US', 'SG']`. Retrieves 12 regulations across FINTRAC, OFAC/FinCEN, and MAS.
4. **Leg 4 (Court Deliberation)**:
   - 🔴 **Prosecutor**: Files Charge under FATF Recommendation 16 and Canadian PCMLTFA (`CA-FINTRAC-TRAVEL-001`). Demands immediate protective hold.
   - 🟢 **Defense**: Argues parties are verified institutions and sanctions are clear. Requests outbox cure window.
   - ⚖️ **CCO**: **VERDICT: REVIEW**. Pre-execution policy prohibits unanchored cross-border transfers. Orders automated on-chain protective hold.
5. **Leg 5 (Dispatch)**: Dispatches `freezeSettlement(...)` to SettlementHub contract. Probes block receipt and confirms contract state `isSettlementHeld(id) == True`.
6. **Leg 6 (Audit)**: Hashes case facts into canonical SHA-256 digest `0x912859d0...` and computes Merkle Root.

---

### Case 2: Internal Bank Transfers & Binance-Style Hack Prevention

**Context**: High-volume internal omnibus sweep of $5,000,000.00 USDC without verified natural-person beneficial ownership (commingling risk), or rogue internal self-settlement wash trading.

**Commands**:
```bash
# Test 1: Commingled omnibus sweep lacking beneficial ownership
python scripts/e2e_compliance_runner.py --scenario binance_hack

# Test 2: Circular wash trade / rogue employee sweep (Self-settlement)
python scripts/e2e_compliance_runner.py --wash-trade

# Test 3: Unanchored zero-hash evasion attempt
python scripts/e2e_compliance_runner.py --zero-instructions-hash
```

**Enforcement Outcomes**:
- **Wash Trade Protection**: Leg 1 Intake catches `initiator == beneficiary` immediately and rejects transaction with `ValidationError: Self-settlement prohibited: initiator and beneficiary wallets cannot be identical`. Zero gas wasted, zero state created.
- **Zero-Hash Protection**: Evasion attempts submitting `0x00...00` instructions hash are rejected with `ValidationError: Settlement ID, participant wallets, and instructions hash must be nonzero`.
- **Omnibus Commingling**: Prosecutor charges under `US-BSA-AML-COMMINGLING`. CCO orders protective freeze on SettlementHub, preventing unauthorized capital flight before funds can be drained.

---

### Case 3: Multihop Correspondent Routing Decided Strictly by Rules

**Context**: Originator is authorized at Scotiabank (Hop 0), but intermediary correspondent bank JPMorgan Chase (Hop 1) enforces strict `ALL_ROUTE_POSITIONS` admission policy and has not vetted this originator.

**Command**:
```bash
python scripts/e2e_compliance_runner.py --scenario multihop_routing
```

**Court Execution Trace**:
1. **Leg 2 (Admission)**:
   - `[PASS]` Hop 0 (Scotiabank): Policy `scotiabank-originator-allowlist` -> `ORIGINATOR_ALLOWLISTED`
   - `[DENY]` Hop 1 (JPMorgan Chase): Policy `jpmorgan_chase-originator-allowlist` -> `ORIGINATOR_NOT_ALLOWLISTED`
2. **Leg 4 (Court Deliberation)**:
   - 🔴 **Prosecutor**: Argues corridor breach: Intermediary bank admission policy strictly violated.
   - 🟢 **Defense**: Requests officer review citing key rotation delay.
   - ⚖️ **CCO**: **VERDICT: DENY**. Adjudication: Defense overruled. Correspondent banking admission is non-waivable. Orders `QUARANTINE_REJECT` and protective hold.
3. **Leg 5 (Dispatch)**: Settlement frozen on-chain. Intermediary corridor transit denied.

---

## 5. Live Public Ethereum Sepolia Blockchain Proofs

Every protective action, contract call, and routed settlement executed by ChainLex is anchored to the public **Ethereum Sepolia** testnet, inspectable on Etherscan:

| Action / Milestone | Sepolia Contract / Transaction | Verified On-Chain State | Public Etherscan Link |
| :--- | :--- | :--- | :--- |
| **SettlementHub Contract** | `0xABD45d376b0aA6dB71518b719D5f7E1e168cC4FB` | Deployed bytecode (`contracts/SettlementHub.sol`, Paris EVM) | [View Contract](https://sepolia.etherscan.io/address/0xABD45d376b0aA6dB71518b719D5f7E1e168cC4FB) |
| **Contract Deployment Tx** | `0x3571a7f787af7377cc1f47f13a7c004aad5387a57a20418c8013acd6157a1316` | Deployed by Operator `0xBCfe8323...` | [View Deployment Tx](https://sepolia.etherscan.io/tx/3571a7f787af7377cc1f47f13a7c004aad5387a57a20418c8013acd6157a1316) |
| **Multi-Hop Routed Settlement Tx** | `0x8634ed85c32a9ae8ff0acf75e11b32a866fc4a55df7be983218bd5ed1f24dba5` | Emitted `SettlementInitiatedV2` with route `[scotiabank, jpmorgan_chase, dbs]` | [View Routed Settlement Tx](https://sepolia.etherscan.io/tx/8634ed85c32a9ae8ff0acf75e11b32a866fc4a55df7be983218bd5ed1f24dba5) |
| **Automated Compliance Freeze Tx** | `0x86aab550f38906957835bdc093826b49661f58566a10f402028b152c58991956` | Emitted `SettlementFrozen`; verified `isSettlementHeld(...) == True` | [View Compliance Freeze Tx](https://sepolia.etherscan.io/tx/0x86aab550f38906957835bdc093826b49661f58566a10f402028b152c58991956) |

---

## 6. How to Run Custom Transactions & Verify

### Running a Custom Compliant Transaction
```bash
python scripts/e2e_compliance_runner.py \
  --origin-bank scotiabank \
  --origin-country CA \
  --inter-bank jpmorgan_chase \
  --inter-country US \
  --dest-bank dbs \
  --dest-country SG \
  --amount 100000.0 \
  --symbol USDC
```
**Outcome**: All 3 agents approve (`PASS`). No hold dispatched. Route cleared for atomic settlement.

### Running a Transaction from a JSON File
```bash
python scripts/e2e_compliance_runner.py \
  --tx-file data/country_rules/settlement_transaction_example.json \
  --report-out audit_report.json
```
**Outcome**: Ingests route and settlement details directly from JSON, runs the 6-leg pipeline, and outputs a complete, auditable JSON report to `audit_report.json`.

---

## 7. Automated Test Suite Validation

The test suite validates both the dynamic test runner and all domain models, FSM state transitions, and EVM connectors:

```bash
# Run the complete test suite
PYTHONPATH=src .venv/bin/pytest

# Run the dynamic E2E compliance runner tests specifically
PYTHONPATH=src .venv/bin/pytest tests/test_e2e_compliance_runner.py -v

# Run code style & static analysis
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

**Results**:
- **153 passing automated tests**, 3 skipped (only for offline Atlas mock integration).
- **0 errors** on `ruff check .`
- **0 formatting discrepancies** on `ruff format`.
