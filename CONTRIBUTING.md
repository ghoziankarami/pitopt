# Contributing

Use Python 3.10 or newer. Create a virtual environment, install `pip install
-e ".[dev]"`, then run `ruff check .` and `pytest`. Before changing engine
behaviour, run independent solver tests and the golden regression gate.
Update expected outputs only after explaining the numerical change.

Contribute synthetic fixtures only. Do not submit customer data, credentials,
private screenshots, recordings or copied code without a compatible license.
Include provenance and license notices for third-party assets.

Do not expose a normal local UI server to the Internet. Public showcases must
use demo mode, a separate synthetic-only root and a reverse proxy with limits.
