# ADR-005 — Identity and policy: properties, not products

**Status:** accepted · **Date:** 2026-08-29

## Context

`LAB-BUILD.md` lists OIDC (Keycloak) and OPA for Stage 1. Neither image is
cached locally; both would need a network pull and a running container.

The reason they are on the list is a specific claim the experiment needs:

> The failure occurred **despite** every action being properly authenticated and
> properly authorized.

That sentence is unavailable if the agent merely asserts who it is, or decides
its own permissions.

## Decision

Implement the **properties** those products provide, and say plainly that they
are not the products.

| Property the experiment needs | How it is provided |
|---|---|
| Identity the agent cannot forge or widen | Signed JWT, issued externally, verified by the service. Tampering and wrong-key signing both rejected — tested. |
| Scoped authority | Scopes in the token; missing scope denies |
| Tenant isolation as a hard invariant | Cross-tenant denied outright, not scored as a percentage |
| Authorization decided **outside** the actor | `libs/policy.py`, evaluated by the service. The agent never calls it. |
| Deterministic decisions | Same inputs, same outcome — asserted over 50 evaluations |

## What this is NOT

Keycloak and OPA bring an operational surface this does not have: token
lifetimes and refresh, key rotation, discovery endpoints, OPA's policy language,
bundle distribution, decision logs. Those matter for a production system.

**They do not change what this experiment measures.** The experiment asks
whether a locally-correct, properly-authorized action can still break an
aggregate invariant. Whether the token came from Keycloak or from
`libs/identity.py` is invisible to that question.

Recording it here rather than letting the substitution pass silently: a reader
comparing the repo to the plan would otherwise find OIDC and OPA listed and
absent, and reasonably wonder what else was quietly dropped.

**If this ever moves toward a client engagement or a production claim, swap in
the real products.** The property boundary above is exactly the diff.

## The boundary that must not move

The policy authorizes **one action at a time** and does not know the aggregate.
Per-action authorization is not aggregate correctness. A policy that enforced
both would be the solution under test, and every finding would become circular —
the system would catch the breach only by being told the rule we are asking
whether anyone knows.

`test_policy_does_not_know_about_the_aggregate_ceiling` enforces this by parsing
the module and checking the **logic**, with docstrings stripped. An earlier
version checked raw source and failed on the module's own explanation of why the
code must not touch the aggregate. Mutation-verified: adding an aggregate check
to the policy fails it.
