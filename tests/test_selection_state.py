"""Browser evidence for delayed callbacks and a newly uploaded unsolved project."""
import os
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip('playwright.sync_api')

from pitopt.ui.server import App, UIServer, make_handler  # noqa: E402


@pytest.fixture
def page(tmp_path):
    (tmp_path / 'projects').mkdir()
    server = UIServer(('127.0.0.1', 0), make_handler(App(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PITOPT_CHROMIUM_EXECUTABLE'),
                                        args=['--disable-gpu', '--disable-dev-shm-usage'])
            pg = browser.new_page()
            pg.route('**/audit-harness', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
            source = os.environ.get('PITOPT_TEST_STORE_SOURCE')
            if source:
                pg.route('**/static/js/store.js', lambda route: route.fulfill(
                    body=Path(source).read_text(), content_type='application/javascript'))
            for variable, route_path in [('PITOPT_TEST_RUN_SOURCE', 'run.js'),
                                         ('PITOPT_TEST_DESIGN_SOURCE', 'design/core.js')]:
                override = os.environ.get(variable)
                if override:
                    def serve_override(path):
                        return lambda route: route.fulfill(body=Path(path).read_text(), content_type='application/javascript')
                    pg.route('**/static/js/' + route_path, serve_override(override))
            pg.goto(f'http://127.0.0.1:{server.server_port}/audit-harness')
            yield pg
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('delayed', ['config', 'results'])
def test_old_selection_cannot_replace_new_config_or_results(page, delayed):
    got = page.evaluate('''async (delayed) => {
      const { S, select } = await import('/static/js/store.js');
      let release, entered;
      const enteredPromise = new Promise(resolve => { entered = resolve; });
      const pending = new Promise(resolve => { release = resolve; });
      const response = (kind, project) => new Response(JSON.stringify(kind === 'config'
        ? { raw: { project }, resolved: {} } : { project }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      window.fetch = async url => {
        const u = new URL(url, location.href), project = u.searchParams.get('project');
        const kind = u.pathname.endsWith('config') ? 'config' : 'results';
        if (project === 'A' && kind === delayed) { entered(); await pending; }
        return response(kind, project);
      };
      const old = select('A', 'project');
      await enteredPromise;
      await select('B', 'project');
      release(); await old;
      return { project: S.project, raw: S.raw.project, results: S.results.project, loading: S.loading };
    }''', delayed)
    assert got == {'project': 'B', 'raw': 'B', 'results': 'B', 'loading': False}


def test_unsolved_project_clears_prior_results_without_requesting_missing_output(page):
    got = page.evaluate('''async () => {
      const { S, select } = await import('/static/js/store.js');
      S.results = { project: 'previous' }; S.raw = { project: 'previous' };
      S.projects = [{ id: 'new', scenarios: [{ id: 'project', has_results: false }] }];
      const requests = [];
      window.fetch = async url => {
        requests.push(url);
        return new Response(JSON.stringify({ raw: { project: 'new' }, resolved: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      };
      const selecting = select('new', 'project');
      const clearedImmediately = S.results === null && S.raw === null;
      await selecting;
      return { clearedImmediately, outputRequests: requests.filter(u => u.includes('/api/results')).length,
               results: S.results, error: S.error, raw: S.raw.project };
    }''')
    assert got == {'clearedImmediately': True, 'outputRequests': 0, 'results': None, 'error': None, 'raw': 'new'}
