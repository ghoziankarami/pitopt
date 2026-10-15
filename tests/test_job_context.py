"""A finished job or a delayed confirmation must not change another selected context."""
import test_selection_state

page = test_selection_state.page


async_case = '''async (returned) => {
  const {S} = await import('/static/js/store.js');
  const {pollJob} = await import('/static/js/run.js');
  S.project = returned ? 'A' : 'B'; S.scenario='project'; S.selectionVersion=3;
  S.results={project:S.project}; S.draft={'economics.products.SN.price':9000};
  S.job={id:'old',project:'A',sourceScenario:'project',scenario:'job_scenario',selectionVersion:1,status:'running',log:[]};
  S.runTarget='job_scenario';
  const requests=[];
  window.fetch=async url => {
    requests.push(url);
    let data=url.startsWith('/api/job') ? {id:'old',project:'A',scenario:'job_scenario',status:'done',log:[]}
      : url.startsWith('/api/projects') ? [] : url.startsWith('/api/config') ? {raw:{}} : {project:'wrong'};
    return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
  };
  await pollJob();
  return {project:S.project,scenario:S.scenario,draft:S.draft,
    selections:requests.filter(u=>u.startsWith('/api/config')||u.startsWith('/api/results'))};
}'''


def test_job_completion_does_not_select_its_scenario_in_another_project(page):
    got = page.evaluate(async_case, False)
    assert got == {'project': 'B', 'scenario': 'project', 'draft': {'economics.products.SN.price': 9000}, 'selections': []}


def test_a_b_a_navigation_does_not_allow_old_completion_to_clear_new_draft(page):
    got = page.evaluate(async_case, True)
    assert got == {'project': 'A', 'scenario': 'project', 'draft': {'economics.products.SN.price': 9000}, 'selections': []}


def test_run_confirmation_is_bound_to_the_selection_that_opened_it(page):
    got = page.evaluate('''async () => {
      const {S}=await import('/static/js/store.js'); const {A}=await import('/static/js/actions.js');
      const {startRun}=await import('/static/js/run.js');
      S.project='A'; S.scenario='project'; S.selectionVersion=1;
      startRun({}); const button=document.querySelector('[data-act=confirmRun]');
      S.project='B'; S.selectionVersion=2;
      const requests=[]; window.fetch=async url=>{requests.push(url);throw Error('must not run');};
      await A.confirmRun(button); return requests;
    }''')
    assert got == []
