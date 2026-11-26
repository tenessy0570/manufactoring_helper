async function checkProductionWorkflow(){
  const a=Alpine.$data(document.body), original=window.fetch;
  let rows=[],sequence=0;
  const recalc=row=>{const t={invention:null,materials:null,manufacturing:null,income:null};for(const e of row.entries)t[e.kind]=(Number(t[e.kind])||0)+Number(e.amount);t.cost=Number(t.invention)+Number(t.materials)+Number(t.manufacturing);t.balance=Number(t.income)-t.cost;t.margin=t.cost?t.balance/t.cost*100:null;row.totals=t;return row;};
  window.fetch=async(url,options={})=>{
    const method=options.method||'GET',body=options.body?JSON.parse(options.body):null;
    if(String(url).includes('/catalog/names'))return new Response(JSON.stringify({names:{34:'Tritanium'},missing_type_ids:[]}),{status:200});
    if(String(url).includes('/catalog/items'))return new Response(JSON.stringify({items:[{type_id:10,name:'Example Rig II'}]}),{status:200});
    if(method==='GET'&&String(url).includes('?'))return new Response(JSON.stringify(rows),{status:200});
    let result;
    if(method==='POST'&&url==='/api/v1/productions'){result=recalc({...body,id:'batch',name:'Example Rig II',entries:[]});rows=[result];}
    else if(String(url).endsWith('/purchase-list')){if(body.kind==='materials'&&(body.manufacturing_runs!==125||'units' in body))throw Error('Must send entered manufacturing runs, not planned units');return new Response(JSON.stringify({materials:[{type_id:34,quantity:body.kind==='invention'?10:20}],description:'Purchase materials',stale:false}),{status:200});}
    else if(String(url).endsWith('/estimate'))result={amount:body.decryptor_id===null?'200':'123.45',description:'Market estimate',stale:false,complete_comparison:true,decryptor_options:[{decryptor_id:null,name:'No decryptor',estimated_cost:'200',is_best:false},{decryptor_id:34201,name:'Accelerant',estimated_cost:'123.45',is_best:true}]};
    else if(String(url).endsWith('/entries')){rows[0].entries.push({...body,id:'e'+(++sequence),created_at:new Date().toISOString()});result=recalc(rows[0]);}
    else if(String(url).includes('/entries/')){const id=String(url).split('/').pop();if(method==='DELETE')rows[0].entries=rows[0].entries.filter(e=>e.id!==id);else Object.assign(rows[0].entries.find(e=>e.id===id),body);result=recalc(rows[0]);}
    else if(method==='PUT'){Object.assign(rows[0],body);result=rows[0];}
    else result=rows[0];
    return new Response(JSON.stringify(result),{status:200});
  };
  try{
    a.startCreate();a.searchText='Example';await a.search();await a.$nextTick();
    const editor=document.querySelector('.production-editor');
    if(getComputedStyle(editor).overflowY==='hidden')throw Error('Blueprint suggestions clipped by editor');
    a.choose(a.matches[0]);await a.create();
    if(!a.selected||a.selected.units!==null||a.selected.entries.length)throw Error('Empty production');
    if(!document.querySelector('.production-details').open)throw Error('Batch details must start expanded');
    const saveBar=document.querySelector('.production-save-bar');
    window.scrollTo(0,document.body.scrollHeight);await new Promise(resolve=>setTimeout(resolve,50));
    const saveBounds=saveBar.getBoundingClientRect();
    if(saveBounds.top<0||saveBounds.bottom>innerHeight||saveBar.querySelector('button').form?.id!=='production-details-form')throw Error('Save details must remain visible while scrolling and submit its form');
    window.scrollTo(0,0);

    if([...document.querySelectorAll('.production-list-heading+* th, .market-panel th')].some(th=>th.textContent.trim()==='BPC runs'))throw Error('Unused BPC runs column must be removed');
    if(document.querySelector('input[x-model="details.actual_runs"]'))throw Error('Stored BPC runs field must be removed');
    if(document.querySelectorAll('input[x-model="purchaseRuns"]').length!==1)throw Error('Manufacturing runs input must appear once');
    await a.copyMaterials('materials');
    if(!a.error.includes('manufacturing runs'))throw Error('Empty runs must be rejected without entered runs');
    a.error='';
    a.details.units='150';a.purchaseRuns='125';
    if('actual_runs' in a.buildDetailsPayload())throw Error('Legacy runs must not be submitted with details');
    const originalWrite=Object.getOwnPropertyDescriptor(navigator,'clipboard');
    let copied='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{copied=text;}}});
    try {
      await a.copyMaterials('invention');if(copied!=='Tritanium\t10')throw Error('Invention purchase list');
      await a.copyMaterials('materials');if(copied!=='Tritanium\t20'||a.selected.entries.length)throw Error('Manufacturing purchase must not create expenses');
    } finally {if(originalWrite)Object.defineProperty(navigator,'clipboard',originalWrite);else delete navigator.clipboard;}
    await a.prepareExpense('invention');
    if(a.entry.kind!=='invention'||a.estimateUnits!=='150'||a.entry.amount!=='123.45')throw Error('Invention expense preparation');
    await a.prepareExpense('materials');
    if(a.entry.kind!=='materials'||a.estimateRuns!=='125'||a.entry.amount!=='123.45')throw Error('Actual material quantity preparation');
    await a.prepareExpense('manufacturing');
    if(a.entry.kind!=='manufacturing'||a.estimateRuns!=='125'||a.entry.amount!=='123.45')throw Error('Production installation expense preparation');
    if(![...document.querySelectorAll('.production-purchases button')].some(b=>b.textContent.includes('Fill production expense')))throw Error('Missing production expense action');
    const tones=['invention','materials','manufacturing'].map(kind=>getComputedStyle(document.querySelector('.production-purchases .'+kind+'-action')).backgroundColor);
    if(new Set(tones).size!==3)throw Error('Expense category buttons must use distinct colors');
    a.resetEntry('invention');
    a.estimateUnits='150';
    await new Promise(resolve=>setTimeout(resolve,400));await a.$nextTick();
    if(a.entry.amount!==''||a.inventionOptions.length!==2||a.selected.entries.length)throw Error('Choices must load before fill without inserting amount');
    if(a.decryptorChoice!=='34201')throw Error('Best decryptor must be selected by default');
    const picker=document.querySelector('.decryptor-picker');picker.open=true;await a.$nextTick();
    for(const row of document.querySelectorAll('.decryptor-option')){
      const radio=row.querySelector('input').getBoundingClientRect();
      const icon=[...row.querySelectorAll('img,svg')].find(el=>getComputedStyle(el).display!=='none').getBoundingClientRect();
      const name=row.querySelector('strong').getBoundingClientRect();
      if(!(radio.right<=icon.left+1&&icon.right<=name.left+1)||row.getBoundingClientRect().height>95)
        throw Error('Decryptor options must be compact horizontal rows');
    }

    const none=document.querySelector('input[name="expense-decryptor"][value="none"]');
    none.click();await a.$nextTick();
    if(a.entry.amount!=='')throw Error('Choosing a decryptor filled amount prematurely');
    if(a.decryptorChoice!=='none')throw Error('Radio choice not applied');
    if(!document.querySelector('.decryptor-option img')||!document.querySelector('.decryptor-option svg'))throw Error('Missing decryptor icons');
    await a.estimate();
    if(a.entry.amount!=='200'||a.selected.entries.length)throw Error('Fill must use chosen no decryptor');
    picker.open=true;document.querySelector('input[name="expense-decryptor"][value="34201"]').click();await a.$nextTick();
    if(a.entry.amount!=='200')throw Error('Selection must preserve entered amount until Fill');
    await a.estimate();
    if(a.entry.amount!=='123.45')throw Error('Fill must use selected decryptor');
    await a.saveEntry();
    for(const amount of ['50','100']){a.resetEntry('income');a.entry.amount=amount;await a.saveEntry();}
    if(Number(a.selected.totals.income)!==150)throw Error('Partial sales do not accumulate');
    a.details.units='300';a.details.actual_units='275';await a.saveDetails();
    if(a.selected.entries.length!==3||a.selected.units!==300||a.selected.actual_units!==275)throw Error('Batch extension changed expenses');
    a.editEntry(a.selected.entries[2]);a.entry.amount='110';await a.saveEntry();
    if(a.selected.totals.income!==160)throw Error('Income correction');
    const oldConfirm=window.confirm;window.confirm=()=>true;try{await a.removeEntry(a.selected.entries[1]);}finally{window.confirm=oldConfirm;}
    if(a.selected.totals.income!==110)throw Error('Income deletion');
    a.selected=null;await a.load();await a.open(a.items[0]);await a.$nextTick();
    if(a.selected.entries.length!==2||a.busy)throw Error('Reopen history');
    const oldAmount=a.entry.amount;a.requestApi=async()=>{throw Error('Temporary failure');};await a.estimate();
    if(!a.error||!a.selected||a.entry.amount!==oldAmount)throw Error('Failure lost entry');
    return 'PASS: empty production, estimates, additional batch, partial income and corrections';
  }finally{clearTimeout(a.optionsTimer);a.optionsSequence++;window.fetch=original;}
}
