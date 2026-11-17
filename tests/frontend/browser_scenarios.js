/* Run in an isolated browser on /?demo=1 after Alpine has initialized. */
async function checkFrontendWorkflow() {
  const app = Alpine.$data(document.body);
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  check(app.demo, 'Browser scenarios require sample mode');
  check(!app.error && app.page.items.length > 0, 'Initial opportunities load');
  app.filtersOpen = true;
  await app.$nextTick();
  check([...document.querySelectorAll('[x-model^="form."]')].every(
    control => control.closest('form')?.id === 'opportunity-filters'
  ), 'All filters belong to one form');

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
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:100}) === '6d 1h 36m', 'One-line time uses full runs and Industry V / Advanced Industry III');
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:0}) === '0s', 'No complete runs takes zero time');
  check(app.demandDuration({seconds:'7200',full_runs_at_buy_price:null}) === 'Not available', 'Sell pricing does not invent a demand duration');
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
  const options=['None','Accelerant','Attainment','Augmentation','Optimized Attainment','Optimized Augmentation','Parity','Process','Symmetry'].map((name,i)=>({plan:{decryptor_name:name,decryptor_id:i||null,probability:0.487+i/100},expected_cost_per_unit:String(47000+i*12345.6789)}));
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
  check(!app.demandWarning('single_buy_order').includes('_'), 'Demand warnings are explained');
  check(app.inventionStatus({request:{status:'missing_prices'},stale:false}).includes('prices'), 'Invention status is explained');
  app.$refs.dialog.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true}));
  check(document.activeElement.getAttribute('aria-label') === 'Close item details', 'Dialog traps Tab');
  window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
  await app.$nextTick();
  check(!app.selected && document.activeElement === row, 'Escape restores row focus');
  check(!document.body.style.overflow, 'Closing restores page scrolling');

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
