"""Shared, dependency-free schema of the verified public FINRA file."""

# Verified against the complete public 2026-09-30 download on 2026-10-16.
COLUMNS = (
    "accountingYearMonthNumber",
    "symbolCode",
    "issueName",
    "issuerServicesGroupExchangeCode",
    "marketClassCode",
    "currentShortPositionQuantity",
    "previousShortPositionQuantity",
    "stockSplitFlag",
    "averageDailyVolumeQuantity",
    "daysToCoverQuantity",
    "revisionFlag",
    "changePercent",
    "changePreviousNumber",
    "settlementDate",
)
