"""A delayed design fetch must not overwrite a newer project or parameter response."""
import test_selection_state

page = test_selection_state.page


def test_delayed_design_state_preserves_the_new_project(page):
    got = page.evaluate('''async () => {
      const {S}=await import('/static/js/store.js'); const {D,ensure,loadState}=await import('/static/js/design/core.js');
      let release; const pending=new Promise(resolve=>{release=resolve;});
      window.fetch=async (url,options)=> {
        const body=options.body ? JSON.parse(options.body):{};
        if(body.project==='A') await pending;
        return new Response(JSON.stringify({has_results:false,project:body.project}),{status:200,headers:{'Content-Type':'application/json'}});
      };
      S.project='A'; S.scenario='project'; S.selectionVersion=1; ensure();
      S.project='B'; S.selectionVersion=2; ensure(); await loadState();
      release(); await new Promise(resolve=>setTimeout(resolve,50));
      return {key:D.key,project:D.state.project};
    }''')
    assert got == {'key': 'B/project', 'project': 'B'}


def test_later_parameter_response_wins_even_when_project_is_unchanged(page):
    got = page.evaluate('''async () => {
      const {S}=await import('/static/js/store.js'); const {D,loadState}=await import('/static/js/design/core.js');
      S.project='A';S.scenario='project';S.selectionVersion=1;D.key='A/project';
      let release; const pending=new Promise(resolve=>{release=resolve;}); let n=0;
      window.fetch=async()=> {
        const request=++n;if(request===1)await pending;
        return new Response(JSON.stringify({has_results:false,request}),{status:200,headers:{'Content-Type':'application/json'}});
      };
      const old=loadState();await loadState();release();await old;return D.state.request;
    }''')
    assert got == 2
