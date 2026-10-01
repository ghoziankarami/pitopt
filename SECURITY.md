# Security

PitOpt is a local single-user tool, not a multi-tenant production service.
It binds to loopback. Host/Origin and X-PitOpt checks reduce cross-site attacks;
they are not authentication. Anyone with direct access can modify local projects.

Public demos must run with `--demo`, use a dedicated synthetic-only root, and
be placed behind TLS and request/concurrency limits. Demo still computes bench
geometry, serves downloads and reads project configuration. It does not provide
per-user sessions or isolation; expensive requests can exhaust resources.

For a suspected vulnerability use GitHub private vulnerability reporting when
available; otherwise contact the repository owner privately. Do not include
secrets or private models in public issues. Versions before the publication
audit have not been hardened for untrusted Internet access.
