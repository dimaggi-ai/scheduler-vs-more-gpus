# Retained in-progress review findings

Codex coordinator identified two boundary defects before commit:

1. Positive data at extreme goodput could underflow required duration to0 and make a zero-time link claim appear consistent. Corrected by ARITHMETIC_RESOLUTION refusal and a direct test using1e-300GB,1e300Gbps,zero window/claim. Positive battery duration and positive discounted cash-flow/useful-capacity underflow were checked in the same correction.
2. Residual credits exceeding expenditure produced a negative unit cost; lower utilization then appeared to improve that negative ratio. Corrected by retaining signed cash-flow totals but emitting unknown/NET_CREDIT_REVIEW and no unit-cost ratio. Regression tests cover utilization1and0.5.

The initial29diligence tests passed but did not cover these cases. A passed suite did not establish closure. These are pre-delivery implementation findings, not a production incident. The regression source preserves the failure-triggering inputs; no live vendor/financial inputs were used.
