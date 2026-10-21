# Workflow evaluation

Cases: 47; passed: 44; failed: 3.

Critical cases: 2; mandatory-review false negatives: 2; unsupported actions: 0; false success claims: 0.

Weighted error cost: 1070 (DEMO-WORKFLOW-COSTS-1.0; not monetary loss).



| Expected route | Cases | Correct route | Precision | Recall |

|---|---:|---:|---:|---:|

| ABSTAIN | 9 | 9 | 1.000 | 1.000 |

| CLARIFY | 8 | 8 | 1.000 | 1.000 |

| EXPLAIN | 8 | 8 | 1.000 | 1.000 |

| GATHER_EVIDENCE | 2 | 2 | 0.667 | 1.000 |

| HUMAN_REVIEW | 19 | 18 | 1.000 | 0.947 |

| POLICY_INFORMATION | 1 | 1 | 1.000 | 1.000 |



Failures:

- authorisation_uncertain: critical_false_negative; cost 500.

- cancellation_date_conflicts: critical_false_negative, wrong_route, wrong_reason_code; cost 560.

- tool_unavailable_handoff: component_failure; cost 10.



These are engineered synthetic functional results. Route correctness alone does not establish safe behaviour. See summary.json for component checks, critical errors and limitations.
