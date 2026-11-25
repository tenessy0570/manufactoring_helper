async function checkCalculatorWorkflow(){
  const a=Alpine.$data(document.body),original=window.fetch;
  const requests=[],oldStorage=localStorage.getItem('eve-manufacturing.settings.v1.live');
  if(!a.calculator||a.page.items.length)throw Error('Calculator must not load all opportunities on entry');
  window.fetch=async(url,options={})=>{
    requests.push(String(url));
    if(String(url).includes('/catalog/items'))return new Response(JSON.stringify({items:[{type_id:2048,name:'Damage Control II'},{type_id:31796,name:'Medium Core Defense Field Extender II'}]}));
    if(String(url).includes('/manufacturing/opportunities'))throw Error('Calculator made a bulk request');
    if(String(url).includes('/catalog/names'))return new Response(JSON.stringify({names:{34:'Tritanium'},missing_type_ids:[]}));
    if(String(url).includes('/manufacturing/calculator/')){const result=a.demoPage(a.form,0),item=result.items[0];result.batch={runs:3,units:3,materials:item.materials,material_cost:100,base_job_cost:5,facility_tax:0,system_cost:0,job_cost:5,invention_cost:0,procurement_broker_fee:0,total_cost:105,gross_revenue:200,sales_tax:14,sales_broker_fee:0,net_revenue:186,profit:81,margin_pct:81,covered_units:3};return new Response(JSON.stringify(result));}
    if(String(url).includes('/invention/'))return new Response(JSON.stringify({queued:true}));
    return new Response(JSON.stringify({}));
  };
  try{
    a.blueprint.name='Damage Control II Blueprint';a.invalidateBlueprint();await a.searchBlueprint();
    a.blueprintKey({key:'ArrowDown',preventDefault(){}});a.blueprintKey({key:'Enter',preventDefault(){}});
    if(requests.some(url=>url.includes('/catalog/items')&&url.includes('meta_group_ids')))throw Error('Manual search limited to mass-production meta groups');
    if(Number(a.blueprint.type_id)!==2048||a.blueprintOpen)throw Error('Blueprint keyboard selection');
    await a.$nextTick();const icon=document.querySelector('.calculator-selected-icon');
    if(!icon||!icon.src.includes('/2048/icon')||!document.getElementById('calculator-blueprint').classList.contains('has-item-icon'))throw Error('Selected blueprint icon is missing');
    if(requests.some(url=>url.includes('/manufacturing/')))throw Error('Selection calculated before Show results');
    await a.$nextTick();const input=document.getElementById('calculator-blueprint');input.dispatchEvent(new FocusEvent('focus'));await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,50));
    if(document.getElementById('calculator-matches').getBoundingClientRect().height>0)throw Error('Selected blueprint reopened suggestions');
    a.blueprint.name='Damage';a.invalidateBlueprint();await a.searchBlueprint();await a.$nextTick();
    const suggestions=document.getElementById('calculator-matches').getBoundingClientRect(),runs=document.querySelector('[aria-label="Manufacturing runs"]').getBoundingClientRect();
    if(suggestions.bottom>runs.top)throw Error('Suggestions cover manufacturing runs');
    document.querySelector('.calculator-heading h1').click();await a.$nextTick();
    if(a.blueprintOpen)throw Error('Outside click did not close suggestions');
    input.focus();a.blueprintOpen=false;input.dispatchEvent(new KeyboardEvent('keydown',{key:'Control',ctrlKey:true,bubbles:true}));await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,50));
    if(!a.blueprintOpen||!a.blueprintMatches.length||a.blueprint.name!=='Damage')throw Error('Ctrl failed to reopen unchanged search');
    a.chooseBlueprint({type_id:2048,name:'Damage Control II'});await a.$nextTick();
    input.dispatchEvent(new KeyboardEvent('keydown',{key:'Control',ctrlKey:true,bubbles:true}));await a.$nextTick();
    if(!a.blueprintOpen||Number(a.blueprint.type_id)!==2048)throw Error('Ctrl cleared selected blueprint');
    a.chooseBlueprint({type_id:2048,name:'Damage Control II'});
    a.form.manufacturing_runs='3';a.form.sales_tax='7';a.form.material_hub_id='amarr';
    await a.$nextTick();document.querySelector('[form="calculator-form"][type=submit]').click();
    await new Promise(resolve=>setTimeout(resolve,100));await a.$nextTick();
    const request=requests.find(url=>url.includes('/manufacturing/calculator/2048'));
    if(document.querySelector('[x-model="form.min_margin"]')||document.querySelector('[x-model="form.rank_by"]'))throw Error('Candidate filters leaked into calculator');
    if(!request||!request.includes('manufacturing_runs=3')||request.includes('min_margin')||!request.includes('sales_tax=7')||!request.includes('material_hub_id=amarr'))throw Error('Calculator settings not sent');
    if(a.page.items.length!==1||a.page.items[0].type_id!==2048)throw Error('Calculator result not scoped');
    a.blueprint.name='Medium';a.invalidateBlueprint();await a.load();
    if(!a.error||a.page.items[0].type_id!==2048||!a.hasChanges)throw Error('Typing lost applied result or caused broad calculation');
    a.chooseBlueprint({type_id:31796,name:'Medium Core Defense Field Extender II'});await a.load(false,0);
    if(a.page.items[0].type_id!==31796)throw Error('Selected item not changed');
    await a.$nextTick();window.scrollTo(0,document.body.scrollHeight);await new Promise(resolve=>setTimeout(resolve,30));
    const calculate=document.querySelector('[form="calculator-form"][type=submit]').getBoundingClientRect();
    if(calculate.top<0||calculate.bottom>innerHeight)throw Error('Calculate button not visible after scrolling');window.scrollTo(0,0);
    await a.prepareMarketInvention();
    if(!requests.some(url=>url.includes('/invention/31796/prepare?'))||requests.some(url=>url.includes('/invention/prepare?')))throw Error('Invention preparation must target only selected item');
    a.saveSettings();a.form=a.getDefaultSettings();a.blueprint={type_id:'',name:''};a.restoreSettings();
    if(a.form.sales_tax!=='7'||Number(a.blueprint.type_id)!==31796)throw Error('Calculator persistence');
    if(localStorage.getItem('eve-manufacturing.settings.v1.live')!==oldStorage)throw Error('Calculator changed Opportunities preferences');
    return 'PASS: calculator search, single-item requests, shared settings, private browser namespace and scoped invention';
  }finally{window.fetch=original;}
}
