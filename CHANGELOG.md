# Changelog

Notable changes to PitOpt. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Public demo: every action that needs a local install opens a "Use your own
  data" page with install steps instead of an error message.
- Phone layout for the web UI.
- Community files: code of conduct, issue and pull-request templates, citation file.

### Fixed
- The launcher now finds Python 3.10+ and explains clearly when only an older
  Python is installed, instead of failing inside pip.
- An interrupted first install no longer leaves a broken `.venv` behind.
- First launch generates the synthetic examples and runs the tin example, so
  the app no longer opens on an empty project whose run fails.
- The web UI could hang on "Loading PitOpt…" when the browser fetched its
  modules faster than the server's connection backlog allowed.

### Changed
- Clarify source installation, workflow, and numerical limitations.
- Check human authorship metadata for new contributions.
- README shortened to an introduction; the full reference moved to
  `docs/TECHNICAL.md`.

## [0.4.0] - 2026-10-01

First public release.
