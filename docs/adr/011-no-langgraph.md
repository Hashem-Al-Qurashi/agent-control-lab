# ADR-011 — No LangGraph, and no agent framework at all

**Status:** accepted · **Date:** 2026-08-29

## Context

`LAB-BUILD.md` lists "LangGraph persistence" in the Stage 1 baseline, and the
2×2 design describes LangGraph as the cognition layer.

## Decision

The agents are plain Python. No LangGraph, no framework.

## Why

**The tested arm has no model in it.** The diligent deterministic agent exists
precisely so a failure cannot be blamed on a hallucination, a bad tool choice or
a prompt. A cognition framework has nothing to orchestrate when the policy is
twelve lines of arithmetic and a comparison.

Adding it would import checkpointing, state machines and tool-node machinery in
order to run a function that reads two numbers and compares them to a third. That
enlarges the surface a reviewer must trust without making any finding more
trustworthy.

There is also a specific hazard. Published work has found real concurrency
anomalies *inside* agent frameworks — tool-effect reordering in LangGraph's
ToolNode, with machine-checked proofs (arXiv 2606.17182). Running the experiment
on top of a framework with known anomalies at the layer under test would make
every result ambiguous: framework defect, or the property being claimed?

**Plain Python removes that ambiguity entirely.**

## What this costs

- The LLM arms (C/D) would want a framework, or at least structured tool calling.
  ADR-008 records that those are blocked on credentials anyway.
- A reader expecting LangGraph in an agent-reliability repo will notice its
  absence. That is what this ADR is for.

## What would change this

Building arms C and D. At that point cognition genuinely needs orchestrating, and
the trade — framework surface against structured tool calling — becomes worth
making. The agent entrypoint is already shaped for it: `run_case(case_id, config,
clients)` with the policy's read-check-write replaced by a model call.
