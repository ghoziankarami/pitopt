# Contributing

Thanks for helping improve PitOpt. Bug reports, feature ideas, documentation
fixes and code are all welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Report a bug or suggest a feature

Open an [issue](https://github.com/ghoziankarami/pitopt/issues/new/choose).
For bugs, include the steps, the error output and your OS and Python version.
Reproduce with a bundled synthetic example where possible; never attach a
confidential block model.

## Development setup

You need Python 3.10 or newer and Git.

```bash
git clone https://github.com/ghoziankarami/pitopt.git
cd pitopt
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

`make help` lists shortcuts (`make check` runs lint and tests).

## Pull requests

- Keep a pull request to one change, and describe what and why.
- Before changing engine behaviour, run the independent solver tests
  (`make cross-check`) and the golden regression tests. Update expected
  outputs only after explaining the numerical change.
- The UI is written in Indonesian with an English dictionary: add an entry to
  `pitopt/ui/static/i18n/en.json` for new text (`tests/test_i18n.py` checks it).
- Add a line to `CHANGELOG.md` for user-visible changes.

## Data and licensing

Contribute synthetic fixtures only. Do not submit customer data, credentials,
private screenshots, recordings or copied code without a compatible license.
Include provenance and license notices for third-party assets. Contributions
are accepted under the project's [MIT License](LICENSE).

Do not expose a normal local UI server to the Internet. Public showcases must
use demo mode, a separate synthetic-only root and a reverse proxy with limits
(see [SECURITY.md](SECURITY.md)).
