"""Content identity for an optimisation run; paths and output locations are not credentials."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .config import ProjectConfig


class StaleResults(ValueError):
    """The stored run no longer describes the current inputs/parameters."""


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(cfg: ProjectConfig) -> dict:
    params = asdict(cfg)
    for key in ('source', 'output'):
        params.pop(key, None)
    inputs = {}
    for section in ('block_model', 'surface'):
        value = params[section].get('path')
        if value:
            path = Path(value)
            inputs[section] = {'file': path.name, 'sha256': file_digest(path)}
            params[section]['path'] = path.name
    # Record scientific owners, not UI assets or installation paths.
    root = Path(__file__).resolve().parent
    owners = sorted(root.glob('core/**/*.py')) + [root / 'config.py', root / 'io/blockmodel.py', root / 'pipeline.py']
    engine = hashlib.sha256()
    for path in owners:
        engine.update(path.relative_to(root).as_posix().encode())
        engine.update(path.read_bytes())
    parameter_sha = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    identity = {'schema_version': 1, 'inputs': inputs, 'parameters_sha256': parameter_sha, 'engine_sha256': engine.hexdigest()}
    identity['sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return identity


def freshness(document: dict, cfg: ProjectConfig) -> dict:
    recorded = document.get('meta', {}).get('input_identity')
    if not recorded:
        return {'status': 'unverified', 'reason': 'Run lama belum memiliki fingerprint. Jalankan ulang untuk memverifikasi hasil.'}
    if not isinstance(recorded, dict) or recorded.get('schema_version') != 1:
        return {'status': 'unverified', 'reason': 'Versi fingerprint belum didukung. Jalankan ulang dengan engine ini.'}
    try:
        current = fingerprint(cfg)
    except (OSError, ValueError) as exc:
        return {'status': 'stale', 'reason': f'Input sekarang tidak dapat diverifikasi: {exc}'}
    if current['sha256'] != recorded.get('sha256'):
        return {'status': 'stale', 'reason': 'Input, parameter, atau engine berubah. Jalankan ulang sebelum menggunakan atau mengekspor hasil.'}
    return {'status': 'current', 'reason': None}
