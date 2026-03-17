# Project Scope

This document defines the current product scope of `opsMind`, its likely evolution path, and the safety principles that should govern future execution or remediation features.

## Current Focus

`opsMind` currently focuses on a single evidence-driven operations flow:

- traffic analytics
- resource analytics
- incident aggregation and evidence chains
- recommendation generation and three-view comparison
- task tracking, artifacts, and diagnosis timeline
- AI-assisted diagnosis, review, and writeback
- read-only executor-driven evidence collection

At this stage, the repository is optimized as an operations diagnosis platform, not as a broad infrastructure control plane.

## What The Project Is Optimized For

The current version is best suited for:

- analyzing entry traffic anomalies
- correlating resource pressure with service symptoms
- producing evidence-backed recommendation drafts
- extending diagnosis via the AI assistant
- collecting extra field evidence through read-only executor plugins

## Evolution Path

Future expansion can happen along the existing product chain rather than by introducing a disconnected platform direction. Natural extensions include:

- moving from read-only evidence collection to controlled execution
- moving from controlled execution to human-approved remediation
- adding dry-run, rollback hints, and blast-radius previews
- strengthening approval, audit, and circuit-breaker controls
- introducing richer remote or cluster execution contexts

This means:

- the current project scope does not reject remediation forever
- but any future execution or remediation capability should be built on top of the current evidence, task, approval, and audit layers

## Safety Principles For Execution And Remediation

If `opsMind` expands into stronger execution or remediation features, the following principles should hold:

- clearly separate analysis, evidence collection, execution, and remediation actions
- require explicit approval for higher-risk actions
- persist execution and remediation output into tasks, traces, artifacts, and evidence chains
- keep auditable records of inputs, outputs, operators, and timestamps
- provide timeout, scope control, and circuit-breaking for potentially risky actions
- prefer rollback or recovery guidance when applicable

The key point is not “never add remediation,” but “never add remediation outside governance boundaries.”

## What The Project Is Not Trying To Be Right Now

The current version is not primarily trying to become:

- a general CMDB platform
- a full-scale host management and permissions backend
- a general CI/CD orchestration platform
- a default-on autonomous remediation system
- a broad operations platform detached from the current diagnosis flow

These areas may be discussed later, but they should not displace the current mainline without explicit design work.

## Guidance For Contributors

If you plan to extend `opsMind`, first identify whether your change:

- strengthens the current diagnosis chain
- improves evidence and explainability
- improves tasks, approval, and auditability
- introduces new execution or remediation actions

If your change belongs to the last category, answer these questions first:

- Does it require approval?
- Does it require explicit authorization?
- Can it be rolled back?
- Does it introduce a new high-risk default behavior?
- Can it be integrated into the current task and evidence system?

## Related Documents

- [Architecture](./architecture.en.md)
- [API Overview](./api-overview.md)
- [Deployment Guide](./deployment.md)
- [Verification Matrix](./verification.md)
- [Release Guide](./release.md)
- [Security](../SECURITY.md)
