# Security Policy

## Supported Scope

`opsMind` currently focuses on local or self-hosted operation analysis workflows.

Security review and responsible disclosure are especially relevant to:

- API endpoints under `api/routes`
- AI provider configuration and request forwarding
- Read-only executor plugins
- Local data persistence under SQLite and artifact storage
- Authentication, secrets, and environment variable handling

## Reporting a Vulnerability

If you believe you have found a security issue, please do not open a public issue first.

Please provide a private report that includes:

- A clear summary of the issue
- Impact assessment
- Reproduction steps or proof of concept
- Affected files, modules, or endpoints
- Suggested mitigation, if available

If direct private contact is not available, open a minimal public issue without exploit details and clearly state that it is a security-sensitive report.

## Response Expectations

When a valid report is received, the project aims to:

- Confirm receipt
- Assess severity and scope
- Prepare a fix or mitigation
- Publish a coordinated update when appropriate

## Operational Boundaries

The current repository is designed around:

- Read-only executor commands by default
- Explicit AI provider configuration
- Local or self-hosted deployment assumptions

Contributors should avoid introducing:

- Default-on write execution paths
- Hard-coded secrets or credentials
- Unsafe shell construction for executor commands
- Unbounded artifact or trace exposure

## Hardening Guidance

When deploying `opsMind`, it is recommended to:

- Keep `.env` and provider keys out of version control
- Restrict executor plugins to trusted environments
- Review Docker, Prometheus, and log source connectivity
- Limit public exposure of the backend unless protected by a gateway or access control layer
