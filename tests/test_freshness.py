"""Input identity, restart/readback and export safety; no historical result silently becomes current."""
import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from pitopt.provenance import StaleResults, fingerprint
from pitopt.ui.server import App, UIServer, make_handler

ROOT = Path(__file__).resolve().parents[1]


def test_replaced_run_during_design_generate_is_not_published(project, monkeypatch):
    import pandas as pd

    from pitopt.ui.design_service import DesignJob, DesignService

    app, folder, _ = project
    service = DesignService(app)
    cfg = service.config('example_tin', 'project')
    key = service._key('example_tin', 'project', cfg)
    path = folder / 'out/example_tin_results.json'

    def replace_run(*_args, **_kwargs):
        path.write_bytes(path.read_bytes())
        return object()

    monkeypatch.setattr('pitopt.ui.design_service.build_design', replace_run)
    monkeypatch.setattr(service, '_raster_tier', lambda *_args: None)
    job = DesignJob('example_tin', 'project')
    service._work(job, cfg, pd.DataFrame({'in_pit': [True]}), key)
    assert job.status == 'error'
    assert 'Run optimasi berubah' in job.error
    assert ('example_tin', 'project') not in service.sessions


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / 'projects' / 'example_tin'
    shutil.copytree(ROOT / 'projects/example_tin', folder, ignore=shutil.ignore_patterns('outputs'))
    path = folder / 'project.yaml'
    raw = yaml.safe_load(path.read_text())
    raw['output'] = {'directory': 'out'}
    path.write_text(yaml.safe_dump(raw))
    app = App(tmp_path)
    out = folder / 'out'
    out.mkdir()
    identity = fingerprint(app.config_for('example_tin', 'project'))
    (out / 'example_tin_results.json').write_text(json.dumps({'meta': {'input_identity': identity}, 'kpis': {'npv_plan': 1}}))
    (out / 'example_tin_blocks.csv').write_text('x,y,z\n0,0,0\n')
    return app, folder, path


@pytest.mark.parametrize('change', ['block_model', 'surface', 'parameter'])
def test_changed_source_is_stale_after_restart_and_cannot_be_exported(project, change):
    app, folder, path = project
    assert app.read_results('example_tin', 'project')['freshness']['status'] == 'current'
    raw = yaml.safe_load(path.read_text())
    if change == 'parameter':
        raw['economics']['products'][0]['price'] *= 2
        path.write_text(yaml.safe_dump(raw))
    else:
        target = folder / raw[change]['path']
        target.write_bytes(target.read_bytes() + b'\n')
    reopened = App(app.root)
    assert reopened.result_status('example_tin', 'project')['status'] == 'stale'
    assert not reopened.list_projects()[0]['scenarios'][0]['has_results']
    with pytest.raises(StaleResults):
        reopened.package('example_tin', 'project')
    with pytest.raises(StaleResults):
        reopened.block_table('example_tin', 'project')
    assert (folder / 'out/example_tin_results.json').exists()


def test_relocation_and_output_flags_do_not_change_identity(project, tmp_path):
    app, folder, path = project
    before = fingerprint(app.config_for('example_tin', 'project'))
    raw = yaml.safe_load(path.read_text())
    raw['output']['write_pdf'] = False
    path.write_text(yaml.safe_dump(raw))
    assert fingerprint(app.config_for('example_tin', 'project')) == before
    other = tmp_path / 'moved'
    shutil.copytree(folder, other / 'projects/example_tin')
    assert fingerprint(App(other).config_for('example_tin', 'project')) == before


def test_legacy_readback_is_labelled_and_export_requires_rerun(project):
    app, folder, _ = project
    path = folder / 'out/example_tin_results.json'
    path.write_text(json.dumps({'meta': {'schema_version': 1}, 'kpis': {'npv_plan': 1}}))
    assert app.read_results('example_tin', 'project')['freshness']['status'] == 'unverified'
    with pytest.raises(StaleResults):
        app.package('example_tin', 'project')


def test_save_is_validated_exclusive_and_survives_reopen(project):
    app, folder, _ = project
    with pytest.raises(ValueError):
        app.save_scenario('example_tin', 'project', {'economics.products.SN.price': -1}, 'bad')
    assert not (folder / 'bad.yaml').exists()
    slug = app.save_scenario('example_tin', 'project', {'economics.products.SN.price': 40000}, 'new')
    before = (folder / 'new.yaml').read_bytes()
    with pytest.raises(ValueError, match='sudah ada'):
        app.save_scenario('example_tin', 'project', {'economics.products.SN.price': 99999}, 'new')
    reopened = App(app.root)
    assert reopened.config_for('example_tin', slug).economics.products[0].price == 40000
    assert (folder / 'new.yaml').read_bytes() == before
    assert not list(folder.glob('.*.tmp'))


def test_stale_results_and_download_return_conflict(project):
    app, _, path = project
    raw = yaml.safe_load(path.read_text())
    raw['slope']['overall_angle_deg'] = 30
    path.write_text(yaml.safe_dump(raw))
    server = UIServer(('127.0.0.1', 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for route in ['/api/results?project=example_tin&scenario=project',
                      '/api/download?project=example_tin&scenario=project&file=example_tin_blocks.csv',
                      '/api/package?project=example_tin&scenario=project']:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}'+route)
            assert error.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('change', ['input', 'parameter'])
def test_changed_context_during_job_is_not_promoted(project, monkeypatch, change):
    import time

    app, folder, path = project
    result_path = folder / 'out/example_tin_results.json'
    original = result_path.read_bytes()

    def interrupted_run(cfg, **_kwargs):
        identity = fingerprint(cfg)
        staging = Path(cfg.output.directory)
        staging.mkdir(parents=True)
        (staging / 'example_tin_results.json').write_text(json.dumps({'meta': {'input_identity': identity}}))
        (staging / 'example_tin_blocks.csv').write_text('NEW BLOCKS')
        if change == 'input':
            source = Path(cfg.block_model.path)
            source.write_bytes(source.read_bytes() + b'\n')
        else:
            raw = yaml.safe_load(path.read_text())
            raw['economics']['products'][0]['price'] *= 2
            path.write_text(yaml.safe_dump(raw))

    monkeypatch.setattr('pitopt.pipeline.run', interrupted_run)
    job = app.start_run('example_tin', 'project', {}, None)
    deadline = time.monotonic() + 10
    while job.finished is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.status == 'error', job.error
    assert result_path.read_bytes() == original
    assert (folder / 'out/example_tin_blocks.csv').read_text() == 'x,y,z\n0,0,0\n'


def test_cli_failed_write_preserves_previous_output(project, monkeypatch):
    from argparse import Namespace

    from pitopt.cli import _cmd_run

    _, folder, path = project
    target = folder / 'out/example_tin_blocks.csv'
    original = target.read_bytes()

    def failed(cfg, **_kwargs):
        stage = Path(cfg.output.directory)
        stage.mkdir(parents=True)
        (stage / target.name).write_text('PARTIAL')
        raise ValueError('export interrupted')

    monkeypatch.setattr('pitopt.cli.run', failed)
    with pytest.raises(ValueError, match='interrupted'):
        _cmd_run(Namespace(config=str(path), outdir=None, quiet=True))
    assert target.read_bytes() == original
    assert not list(folder.glob('.out.staging-*'))
