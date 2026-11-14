// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../contracts/SettlementHub.sol";

contract SettlementHubTest {
    function details() internal pure returns (SettlementHub.SettlementDetails memory d) {
        d.amountAtomic = 250000000;
        d.assetSymbol = "USDC";
        d.assetDecimals = 6;
        d.assetContract = address(0x3333);
        d.routeId = "scotiabank-jpmorgan-dbs-demo";
        d.institutionIds = new string[](3);
        d.countryCodes = new string[](3);
        d.institutionIds[0] = "scotiabank";
        d.institutionIds[1] = "jpmorgan_chase";
        d.institutionIds[2] = "dbs";
        d.countryCodes[0] = "CA";
        d.countryCodes[1] = "US";
        d.countryCodes[2] = "SG";
        d.instructionsHash = bytes32(uint256(44));
    }

    function testRoutedRequestAndDuplicateRejection() public {
        SettlementHub hub = new SettlementHub();
        SettlementHub.SettlementDetails memory d = details();
        bytes32 id = bytes32(uint256(1));
        hub.initiateRoutedSettlement(id, address(0x2222), d);
        require(hub.routedSettlementExists(id), "Request not recorded");
        require(hub.settlementCounterparty(id) == address(0x2222), "Wrong beneficiary");
        (bool ok,) = address(hub).call(abi.encodeCall(
            hub.initiateRoutedSettlement, (id, address(0x2222), d)
        ));
        require(!ok, "Duplicate request accepted");
    }

    function testRejectRoutingLoop() public {
        SettlementHub hub = new SettlementHub();
        SettlementHub.SettlementDetails memory d = details();
        d.institutionIds[2] = "scotiabank";
        (bool ok,) = address(hub).call(abi.encodeCall(
            hub.initiateRoutedSettlement, (bytes32(uint256(1)), address(0x2222), d)
        ));
        require(!ok, "Routing loop accepted");
    }

    function testRejectCountryLengthMismatch() public {
        SettlementHub hub = new SettlementHub();
        SettlementHub.SettlementDetails memory d = details();
        d.countryCodes = new string[](2);
        (bool ok,) = address(hub).call(abi.encodeCall(
            hub.initiateRoutedSettlement, (bytes32(uint256(1)), address(0x2222), d)
        ));
        require(!ok, "Mismatched route accepted");
    }

    function testLegacyInitiationStillAvailable() public {
        SettlementHub hub = new SettlementHub();
        hub.initiateSettlement(bytes32(uint256(2)), address(0x2222), 100, "USD");
        require(hub.settlementCounterparty(bytes32(uint256(2))) == address(0x2222));
    }
}
