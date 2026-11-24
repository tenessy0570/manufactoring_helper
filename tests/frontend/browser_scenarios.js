/* Run in an isolated browser on /?demo=1 after Alpine has initialized. */
async function checkFrontendWorkflow() {
  const app = Alpine.$data(document.body);
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  check(app.demo, 'Browser scenarios require sample mode');
  const timeBefore=app.progressNow;
  const clocked={stale:false,fresh_until:new Date(timeBefore+1000).toISOString()};
  check(!app.isStale(clocked),'Fresh before deadline');
  app.progressNow=timeBefore+1000;
  check(app.isStale(clocked),'Badge expires at refresh deadline without another API call');
  app.progressNow=timeBefore;

  check(!app.error && app.page.items.length > 0, 'Initial opportunities load');
  app.filtersOpen = true;
  await app.$nextTick();
  check([...document.querySelectorAll('[x-model^="form."]')].every(
    control => control.form?.id === 'opportunity-filters'
  ), 'All filters belong to one form');

  const columnsButton=document.querySelector('[aria-controls="column-options"]');
  columnsButton.click();await app.$nextTick();
  await new Promise(resolve=>setTimeout(resolve,50));
  check(getComputedStyle(document.querySelector('#column-options')).display!=='none','Columns button opens checkbox menu');
  columnsButton.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  app.hiddenColumns=['cost','margin'];
  await app.$nextTick();
  await new Promise(resolve=>setTimeout(resolve,50));
  check(getComputedStyle(document.querySelector('thead th:nth-child(2)')).display==='none','Hidden column header disappears');
  check(getComputedStyle(document.querySelector('tbody tr td:nth-child(2)')).display==='none','Hidden cells match headers');
  app.saveSettings();app.hiddenColumns=[];app.restoreSettings();
  check(!app.columnVisible('cost')&&!app.columnVisible('margin'),'Column choices persist');
  app.hiddenColumns=[];

  check(app.columnOptions.some(c=>c.id==='volumeShare'),'Daily volume share is selectable');
  app.page.items[0].daily_production_units='1000';
  app.page.items[0].daily_units='100';
  app.page.items[0].daily_volume_share_pct='1000';
  await app.$nextTick();
  const share=document.querySelector('td[x-show="columnVisible(\'volumeShare\')"]');
  check(share.textContent.includes('1000.0%')&&share.textContent.includes('built /'),'Volume share shows output and traded quantities');
  check(share.querySelector('strong').classList.contains('negative'),'Output above regional daily volume is highlighted');
  const originalHub = app.resultForm.hub_id;
  app.form.hub_id = originalHub === 'amarr' ? 'hek' : 'amarr';
  check(app.hasChanges && app.resultForm.hub_id === originalHub, 'Drafts do not relabel results');
  await app.load(true);
  check(app.hasChanges && app.resultForm.hub_id === originalHub, 'Reload preserves applied query');
  await app.load(false, 0);
  check(!app.hasChanges && app.resultForm.hub_id === app.form.hub_id, 'Apply updates result context');
  await app.$nextTick();
  check(document.querySelector('[aria-label="Trade hub"]').value === app.form.hub_id, 'Hub select shows actual selection');

  app.form.buy_demand_tolerance_pct='2.5';
  const fees={buy_broker_fee:'1.2',sell_broker_fee:'2.3',sales_tax:'3.4',facility_tax:'0.5',system_cost_index:'4.6'};
  Object.assign(app.form,fees);
  app.profileName = 'Browser check ' + Date.now();
  app.saveBrowserProfile();
  check(!app.profileError && app.browserProfile, 'Save named browser profile');
  app.form.tech = '2';
  app.updateBrowserProfile();
  app.form.tech = '1';
  await app.applyProfile();
  check(app.form.tech === '2', 'Update and reapply profile');
  check(app.form.buy_demand_tolerance_pct==='2.5','Price range saved in profile');
  check(Object.entries(fees).every(([key,value])=>app.form[key]===value&&app.params().get(key)===value),'Five independent percentages survive profile roundtrip and reach API');
  const migrated=app.migrateBrokerSettings({broker_fee:'2',sell_broker_fee:'3'});
  check(migrated.buy_broker_fee==='2'&&migrated.sell_broker_fee==='3'&&!('broker_fee' in migrated),'Legacy broker settings migrate without overriding explicit rates');
  app.form.category = 'Rigs';
  await app.load(false, 0);
  check(app.page.total === 1 && app.page.items[0].type_id === 31796, 'T2 rig selection');
  app.form.product_order_type='buy';app.form.rank_by='demand_profit';app.form.buy_demand_tolerance_pct='2.5';
  await app.load(false,0);
  check(app.page.items[0].profit_at_current_buy_price!==null,'Demand profit is available with buy pricing');

  const row = document.querySelector('tbody tr');
  row.focus();
  await app.openItem(app.page.items[0]);
  await app.$nextTick();
  check(document.querySelector('main').inert, 'Dialog isolates background controls');
  check(app.historyData.days.length===Number(app.resultForm.days),'History matches chosen period');
  check(app.historyChart('average').path.includes('L'),'Price chart has line segments');
  check(app.historyChart('volume').path.includes('Z'),'Volume chart has bars');
  check(document.querySelectorAll('.combined-history svg').length===1,'Price and volume share one chart');
  check(document.querySelectorAll('.combined-history svg path').length===3,'Combined chart includes grid, volume bars and price line');
  const savedHistory=app.historyData,historyApi=app.api;
  try{
    app.demo=false;app.api=async()=>{throw new Error('History offline');};
    await app.loadHistory();check(app.historyError&&app.selected,'History failure leaves item details usable');
    app.api=async()=>({stale:false,state:{},days:[]});await app.loadHistory();
    check(!app.historyError&&!app.historyChart('average').path,'Empty history shows no invented prices');
    app.api=async()=>({stale:true,days:[{date:'2026-01-01',average:'100',volume:0},{date:'2026-01-03',average:'100',volume:5}]});await app.loadHistory();
    check(app.historyChart('average').path.split('M').length===3,'Missing dates break price line');
    check(!app.historyChart('volume').path.includes('NaN'),'Zero volume produces finite bars');
  }finally{app.demo=true;app.api=historyApi;app.historyData=savedHistory;}

  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:100,demand_duration_seconds:'90000'}) === '1d 1h 0m', 'Batch duration uses server total including preparation');
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:100}) === '8d 8h 0m', 'One-line time uses cached duration without applying skills twice');
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:0}) === '0s', 'No complete runs takes zero time');
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:null}) === 'Not available', 'Sell pricing does not invent a demand duration');
  app.appliedForm.production_lines='3';
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:100}) === '2d 20h 0m', 'Parallel lines round up full runs on busiest line');
  app.appliedForm.production_lines='1';
  check(app.duration(59.9) === '1m 0s', 'Duration rounds across minute boundaries');
  check(app.$refs.dialog.querySelector('.material-name').textContent.includes('Tritanium'), 'Materials have readable names');
  const originalNameApi = app.api;
  try {
    app.demo = false;
    delete app.materialNames[34];
    app.api = async () => { throw new Error('Name source unavailable'); };
    await app.loadMaterialNames();
    check(app.materialNamesMessage && app.selected.type_id === 31796, 'Name failure keeps item costs visible');
    app.api = async () => ({names: {'34': 'Tritanium'}, missing_type_ids: []});
    await app.loadMaterialNames();
    check(!app.materialNamesMessage && app.materialName(34) === 'Tritanium', 'Material name retry recovers');
  } finally {
    app.demo = true;
    app.api = originalNameApi;
  }
  const inventionApi = app.api;
  const options=['None','Accelerant','Attainment','Augmentation','Optimized Attainment','Optimized Augmentation','Parity','Process','Symmetry'].map((name,i)=>({plan:{decryptor_name:name,decryptor_id:i||null,probability:0.487+i/100,runs_per_copy:10+i},expected_cost_per_unit:String(47000+i*12345.6789)}));
  const ready={request:{status:'ready',updated_at:new Date().toISOString(),expires_at:new Date(Date.now()+86400000).toISOString(),result:{options,best:options[0],complete_pricing:true}},stale:false,queued:false};
  sessionStorage.setItem('inventionFixture',JSON.stringify(ready));
  try {
    app.demo=false;
    let finishCheck;
    app.api=()=>new Promise(resolve=>{finishCheck=resolve;});
    const checking=app.loadInvention();
    check(app.inventionChecking,'Check status shows progress');
    finishCheck(ready);await checking;
    check(!app.inventionChecking&&app.lastInventionCheck&&app.inventionReady,'Check status shows ready result and timestamp');
    app.invention=null;
    app.api=async()=>({...ready,queued:true,request:{...ready.request,status:'pending'}});
    await app.prepareInvention();
    check(app.inventionMessage.includes('queued'),'Prepare explains queued job');
    app.api=async()=>ready;
    await app.prepareInvention();
    check(app.inventionMessage.includes('no extra job'),'Fresh cache explains why no new job is created');
  } finally {app.demo=true;app.api=inventionApi;}
  await app.$nextTick();
  check(app.$refs.dialog.textContent.includes('10 runs / T2 BPC'),'Candidate invention options show runs per successful copy');
  check(!app.demandWarning('single_buy_order').includes('_'), 'Demand warnings are explained');
  check(app.inventionStatus({request:{status:'missing_prices'},stale:false}).includes('prices'), 'Invention status is explained');
  app.$refs.dialog.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true}));
  check(document.activeElement.getAttribute('aria-label') === 'Close item details', 'Dialog traps Tab');
  window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
  await app.$nextTick();
  check(!app.selected && document.activeElement === row, 'Escape restores row focus');
  check(!document.body.style.overflow, 'Closing restores page scrolling');

  check(app.timeAgo(new Date(app.progressNow-135*60000).toISOString())==='2h 15m ago','Progress uses hours and minutes since snapshot');
  check(app.timeAgo(null)==='not yet loaded','Missing snapshot is explicit');
  const progressApi=app.api;
  try {app.demo=false;app.api=async()=>({catalog_items:100,recipes_loaded:80});await app.loadProgress();check(app.dataProgress.recipes_loaded===80,'Progress shows saved coverage');app.api=async()=>{throw new Error('Offline');};await app.loadProgress();check(app.progressError&&app.dataProgress.recipes_loaded===80,'Progress error preserves last saved coverage');}
  finally{app.demo=true;app.api=progressApi;app.progressError=false;}
  const previousPage = JSON.stringify(app.page);
  const originalApi = app.api;
  try {
    app.demo = false;
    app.api = async () => { throw new Error('Simulated network failure'); };
    await app.load(true, app.page.offset + app.page.limit);
    check(JSON.stringify(app.page) === previousPage, 'Failed pagination preserves rows and offset');
    check(app.error === 'Simulated network failure', 'Network error stays visible');
  } finally {
    app.demo = true;
    app.api = originalApi;
  }
  await app.load(false, 0);
  check(!app.error, 'Retry clears error after success');
  app.saveSettings();
  return 'PASS: filters, applied context, profile update, T2 rigs, keyboard dialog, network recovery';
}
