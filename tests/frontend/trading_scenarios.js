async function checkTradingWorkflow(){
  const a=Alpine.$data(document.body),original=window.fetch,requests=[],historyRequests=[];let fail=0,historyMode='normal',releaseHistory=null;
  window.fetch=async(url,options)=>{
    if(String(url).includes('/api/v1/market/history/')){
      historyRequests.push(String(url));const hub=new URL(String(url),location.origin).searchParams.get('hub_id');
      const fixture={testHub:hub,stale:false,days:[{date:'2026-11-18',average:'120',volume:50},{date:'2026-11-16',average:'100',volume:30}]};
      sessionStorage.setItem('tradingHistoryFixture',JSON.stringify(fixture));
      if(historyMode==='defer')await new Promise(resolve=>releaseHistory=resolve);
      if(historyMode==='error')return new Response('{}',{status:503});
      return new Response(JSON.stringify(historyMode==='empty'?{...fixture,days:[]}:fixture));
    }
    if(!String(url).includes('/api/v1/trading/'))return original(url,options);
    requests.push(String(url));if(fail)return new Response(JSON.stringify({detail:'Temporary trading failure'}),{status:fail});
    return new Response(JSON.stringify({source_hub:'jita',destination_hub:'amarr',total:60,offset:Number(new URL(String(url),location.origin).searchParams.get('offset')),limit:25,scanned:500,missing_metadata:0,missing_volume:0,source_updated_at:new Date().toISOString(),destination_updated_at:new Date().toISOString(),items:[{source_hub:'jita',destination_hub:'amarr',type_id:42,jumps:5,route_highsec:true,profit_per_jump:'94',name:'All-market test item',purchase_price:'100',sale_price:'150',purchase_fee:'0',sale_fee:'3',cost_per_unit:'100',profit_per_unit:'47',margin_pct:'47',volume_m3:'2',profit_per_m3:'23.5',quantity:10,investment:'1000',cargo_m3:'20',batch_revenue:'1470',batch_profit:'470',average_sale_price:'150',source_stock:10,destination_demand:20,source_updated_at:new Date().toISOString(),destination_updated_at:new Date().toISOString(),stale:false,daily_isk_volume:'2500000000',history_updated_at:new Date().toISOString(),instant_trade:true,warnings:[]}]}));
  };
  try{
    a.profileName='Test route';a.saveProfile();const savedId=a.profileId;if(a.profiles.length!==1)throw Error('Profile save failed');a.form.sales_tax='9';a.selectProfile();if(a.form.sales_tax!=='3')throw Error('Profile restore failed');a.form.sales_tax='4';a.saveProfile(true);a.form.sales_tax='8';a.selectProfile();if(a.form.sales_tax!=='4')throw Error('Profile update failed');const originalConfirm=window.confirm;window.confirm=()=>true;a.deleteProfile();window.confirm=originalConfirm;if(a.profiles.length||a.profileId||a.form.sales_tax!=='4')throw Error('Profile deletion changed settings');a.form.sales_tax='3';
    if(a.form.purchase_side!=='sell'||a.form.sale_side!=='buy'||'hauling_per_m3' in a.form)throw Error('Trading defaults');
    if(a.form.source_hub!==''||a.form.destination_hub!=='')throw Error('Hubs selected by default');
    if(a.form.sales_tax!=='3')throw Error('Legacy financial settings were lost');
    if(a.form.filter_daily_turnover!==false||!document.querySelector('[x-model="form.min_daily_isk_volume"]').disabled)throw Error('Turnover filter enabled by default');
    if(a.form.price_spikes_only!==false||a.form.price_spike_threshold!=='30')throw Error('Price spikes enabled by default');
    if(a.form.route_mode!=='safe')throw Error('Unsafe route default');
    await a.load();if(requests.at(-1).includes('source_hub=')||requests.at(-1).includes('destination_hub='))throw Error('All-hub query restricted');
    a.form.source_hub='jita';await a.load();if(!requests.at(-1).includes('source_hub=jita')||requests.at(-1).includes('destination_hub='))throw Error('One-sided route not supported');
    a.form.destination_hub='jita';const before=requests.length;await a.load();if(!a.error||requests.length!==before)throw Error('Same hub accepted');
    a.form.destination_hub='amarr';a.swap();if(a.form.source_hub!=='amarr'||a.form.destination_hub!=='jita')throw Error('Hub swap');a.swap();
    a.form.price_spikes_only=true;a.form.price_spike_threshold='45';
    a.form.route_mode='shortest';a.form.max_jumps='25';a.form.min_profit_per_jump='90';a.form.rank_by='profit_per_jump';
    a.form.sales_tax='2';a.form.max_cargo_m3='1000';a.form.filter_daily_turnover=true;a.form.min_daily_isk_volume='2500000';a.form.history_days='14';
    await a.load();await a.$nextTick();if(a.error||a.page.items[0].name!=='All-market test item')throw Error('Trade result');
    if(requests.at(-1).includes('hauling_per_m3')||!requests.at(-1).includes('max_cargo_m3=1000'))throw Error('Trading settings not sent');
    if(!requests.at(-1).includes('filter_daily_turnover=true'))throw Error('Turnover toggle not sent');
    if(!requests.at(-1).includes('min_daily_isk_volume=2500000')||!requests.at(-1).includes('history_days=14'))throw Error('Daily turnover filter not sent');
    if(!requests.at(-1).includes('price_spikes_only=true')||!requests.at(-1).includes('price_spike_threshold=45'))throw Error('Spike filter not sent');
    if(!requests.at(-1).includes('route_mode=shortest')||!requests.at(-1).includes('max_jumps=25')||!requests.at(-1).includes('min_profit_per_jump=90')||!requests.at(-1).includes('rank_by=profit_per_jump'))throw Error('Route parameters lost');
    if(document.querySelector('td[x-show="isColumnVisible(\'jumpProfit\')"]').textContent!=='94')throw Error('Batch profit per jump missing');
    if(document.querySelector('[x-model="form.hauling_per_m3"]'))throw Error('Hauling tariff still present');
    if(document.querySelector('.trade-density').textContent!=='23.5')throw Error('Profit per cubic meter missing');
    if(!document.querySelector('.trade-route-cell').textContent.includes('Amarr'))throw Error('Trade route missing');
    if(!document.querySelector('.trade-table').textContent.includes('470'))throw Error('Batch profit not rendered');
    if(a.compactMoney('12350000')!=='12.35M'||a.compactMoney(null)!=='--'||a.compactMoney('1250000000')!=='1.25B'||a.compactMoney('2100000000000')!=='2.1T'||a.compactMoney(850000)!=='850K')throw Error('Compact money formatting');
    const columns=document.querySelector('.trade-columns');columns.querySelector('summary').click();await a.$nextTick();
    if(!columns.open||columns.querySelectorAll('input[type=checkbox]').length!==a.columnOptions.length)throw Error('Trading columns menu');
    const priceColumn=[...columns.querySelectorAll('label')].find(label=>label.textContent.includes('Buy / unit'));priceColumn.querySelector('input').click();await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,50));
    if(a.isColumnVisible('purchase')||document.querySelector('th[x-show="isColumnVisible(\'purchase\')"]').getBoundingClientRect().height!==0)throw Error('Price column did not hide');
    if(a.changed)throw Error('Column selection changed calculation settings');
    a.saveColumns();if(!JSON.parse(localStorage.getItem('eve.interhub.columns.v1')).includes('purchase'))throw Error('Column visibility not persisted');
    columns.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));if(columns.open)throw Error('Column picker did not close');
    a.form.destination_hub='hek';a.form.history_days='90';
    const itemButton=document.querySelector('.trade-item-button');itemButton.focus();itemButton.click();
    await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,70));
    const dialog=a.$refs.historyDialog;
    if(!dialog.open||!a.historyData||!historyRequests.at(-1).includes('hub_id=amarr')||!historyRequests.at(-1).includes('days=14'))throw Error('History used draft hub or period instead of selected sale route');
    if(a.historyData.days[0].date!=='2026-11-16'||(a.historyChart('average').path.match(/M/g)||[]).length!==2)throw Error('History sort or chart gaps');
    if((a.historyChart('average').path.match(/h6/g)||[]).length!==2)throw Error('Isolated price days have no visible marks');
    if(document.activeElement!==a.$refs.historyClose||!dialog.querySelector('svg'))throw Error('History dialog focus or graph');
    dialog.dispatchEvent(new Event('cancel',{cancelable:true}));await a.$nextTick();
    if(dialog.open||document.activeElement!==itemButton||document.body.style.overflow==='hidden')throw Error('History close did not restore focus/scroll');
    historyMode='defer';const oldHistory=a.openHistory(a.page.items[0]);await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,30));
    historyMode='normal';await a.openHistory({...a.page.items[0],destination_hub:'hek'});releaseHistory();await oldHistory;
    if(a.historyData.testHub!=='hek'||a.historyItem.destination_hub!=='hek')throw Error('Old history response overwrote new route');a.closeHistory();
    historyMode='error';await a.openHistory(a.page.items[0]);if(!a.historyError||a.historyLoading)throw Error('History error feedback');
    historyMode='normal';await a.loadHistory();if(a.historyError||!a.historyData)throw Error('History retry failed');a.closeHistory();
    historyMode='empty';await a.openHistory(a.page.items[0]);if(a.historyData.days.length)throw Error('Empty history invented data');a.closeHistory();historyMode='normal';
    a.form.destination_hub='amarr';a.form.history_days='14';
    const applied=a.applied;a.form.search='changed';if(!a.changed||a.applied!==applied)throw Error('Draft settings overwrite results');
    fail=503;await a.load();if(!a.error||a.page.items.length!==1)throw Error('Failure erased results');
    fail=0;await a.load();if(a.error||a.changed)throw Error('Trading retry failed');
    await a.load(25,true);if(a.page.offset!==25||!requests.at(-1).includes('offset=25'))throw Error('Pagination');
    a.save();const saved=JSON.parse(localStorage.getItem('eve.interhub.settings.v2'));if(saved.sales_tax!=='2'||saved.source_hub!=='jita')throw Error('Trading persistence');
    a.form.search='';await a.load();
    return 'PASS: interhub defaults, hub swap, costs, applied settings, errors, pagination and persistence';
  }finally{window.fetch=original;}
}
