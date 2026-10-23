# Security Policy

## Supported Versions

Security fixes are applied to the current main branch.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository's
private security-reporting feature and include:

- the affected component;
- reproduction steps;
- expected and observed behavior;
- potential impact;
- any suggested mitigation.

Please avoid including credentials or sensitive production data in reports.
Replace them with synthetic examples.

## Deployment Notes

The bundled Flask server is intended for local development and controlled
networks. Before exposing it externally, add authentication, authorization,
TLS termination, network restrictions, and production-grade request limits.

MQTT credentials must be supplied through environment variables or a secret
manager. Do not commit credentials to the repository.
