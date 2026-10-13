"""Package only verified synthetic demo runtime and its exact installed application wheel."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pitopt
from pitopt.ui.server import App


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--handoff', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    app = App(root)
    projects = ['example_tin', 'porphyry_synthetic']
    assert sorted(p['id'] for p in app.list_projects()) == sorted(projects), 'Only named synthetic demo projects may be published'
    identities = {}
    for name in projects:
        doc = app.read_results(name, 'project', require_current=True)
        assert doc['schedule']['plan'], name
        assert doc['readiness']['operational_design_certified'] is False, name
        identities[name] = doc['meta']['input_identity']
    source = Path(pitopt.__file__).resolve().parent
    expected = {'pitopt/' + p.relative_to(source).as_posix(): p.read_bytes()
                for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    with zipfile.ZipFile(args.wheel) as wheel:
        actual = {n: wheel.read(n) for n in wheel.namelist() if n.startswith('pitopt/') and not n.endswith('/')}
    assert actual == expected, 'Wheel package differs from the engine/UI used to verify the runtime'
    args.outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.outdir) as temporary:
        payload = Path(temporary)
        for name in projects:
            shutil.copytree(root / 'projects' / name, payload / 'runtime/projects' / name)
            output, _ = app.output_dir(name, 'project')
            relative = output.relative_to(root)
            shutil.copytree(output, payload / 'runtime' / relative)
        shutil.copy2(args.wheel, payload / args.wheel.name)
        shutil.copy2(source.parent / 'requirements-tested-py312.txt', payload / 'requirements-tested-py312.txt')
        shutil.copy2(args.handoff, payload / 'LOCAL_DEPLOYMENT.md')
        (payload / 'RUN-IDENTITIES.json').write_text(json.dumps(identities, indent=2) + '\n')
        # Recheck the complete relocated payload before sealing it.
        for name in projects:
            assert App(payload / 'runtime').result_status(name, 'project')['status'] == 'current'
        files = sorted(p for p in payload.rglob('*') if p.is_file())
        assert not any(p.is_symlink() for p in payload.rglob('*')), 'Do not publish symlinks'
        (payload / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(payload).as_posix()}\n' for p in files))
        archive = args.outdir / 'pitopt-synthetic-demo.tar.gz'
        assert not archive.exists(), 'Use a new output directory; release archives are immutable'
        with tarfile.open(archive, 'w:gz') as bundle:
            for path in sorted(payload.iterdir()):
                bundle.add(path, arcname=path.name)
    (args.outdir / 'SHA256SUMS').write_text(f'{digest(archive)}  {archive.name}\n')
    print(json.dumps({'archive': str(archive.resolve()), 'sha256': digest(archive), 'current_projects': projects}))


if __name__ == '__main__':
    main()
