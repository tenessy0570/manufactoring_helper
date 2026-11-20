/* Local application state; all monetary calculations remain on the server. */
document.addEventListener('alpine:init', () => {
  Alpine.data('manufacturingApp', () => ({
    ...window.marketHistoryChartMethods,
    calculator:document.body.dataset.calculator==='true',blueprint:{type_id:'',name:''},blueprintMatches:[],blueprintOpen:false,blueprintIndex:-1,blueprintSequence:0,blueprintSearching:false,blueprintSearchDone:false,appliedBlueprintId:0,
    demo: new URLSearchParams(location.search).get('demo') === '1', loading: false,
    deletingProfile:false,filtersOpen: true, error: '', profileId: '', profiles: [], profileSettings: {},
    historyData:null,historyLoading:false,historyError:'',historyHoverText:'',
    materialNames:{},materialNamesLoading:false,materialNamesMessage:'',preparingMarket:false,preparationMessage:'',
    profileSaveOpen:false,profileName:'',profileError:'',profileWarning:'',storageWarning:'',
    selected: null, invention: null, inventionMessage: '', inventionLoading: false, inventionChecking:false, lastInventionCheck:null,
    requestSequence: 0, detailSequence: 0, appliedForm:null, appliedSettings:{}, returnFocus:null, profileNotice:'',
    hubs: [{id:'jita',name:'Jita'},{id:'amarr',name:'Amarr'},{id:'dodixie',name:'Dodixie'},{id:'rens',name:'Rens'},{id:'hek',name:'Hek'}],
    progressNow:Date.now(),
    isStale(item){return !!item && (item.stale || (!!item.fresh_until && Date.parse(item.fresh_until)<=this.progressNow));},
    staleExplanation(item){
      const labels={recipe:'Manufacturing recipe',product_market:'Product market prices',material_market:'Material market prices',history:'Regional trading history',invention:'Invention estimate'};
      const sources=Object.entries(item?.freshness_deadlines||{}).filter(([,date])=>Date.parse(date)<=this.progressNow).map(([key])=>labels[key]||key);
      return sources.length?'Due for refresh: '+sources.join(', ')+'. Select '+(this.calculator?'Calculate profit':'Show results')+' after the background update.':'Saved inputs are due for refresh. Select '+(this.calculator?'Calculate profit':'Show results')+' after the background update.';
    },
    timeAgo(value){if(!value)return 'not yet loaded';const stamp=new Date(value).getTime();if(!Number.isFinite(stamp))return 'not available';const minutes=Math.floor(Math.max(0,this.progressNow-stamp)/60000);return minutes<1?'less than a minute ago':(minutes>=1440?Math.floor(minutes/1440)+'d ':'')+Math.floor(minutes%1440/60)+'h '+minutes%60+'m ago';},
    dataProgress:null,progressError:false,progressSequence:0,
    async loadProgress(){if(this.demo)return;const seq=++this.progressSequence;try{const result=await this.api('/health/data-progress?hub='+this.resultForm.hub_id);if(seq!==this.progressSequence)return;this.dataProgress=result;this.progressError=false;}catch(_){if(seq===this.progressSequence)this.progressError=true;}},
    hiddenColumns:[], columnOptions:[{id:'cost',label:'Cost / unit'},{id:'profit',label:'Profit / unit'},{id:'demand',label:'Profit on demand'},{id:'margin',label:'Margin'},{id:'daily',label:'Profit / day'},{id:'turnover',label:'Regional turnover / day'},{id:'data',label:'Data freshness'}],
    columnVisible(id){return !this.hiddenColumns.includes(id);},
    form: {}, page: {items:[],total:0,offset:0,limit:25},
    defaults() {return {search:'',hub_id:'jita',material_hub_id:'',tech:'',category:'',
      material_order_type:'sell',product_order_type:'sell',buy_demand_tolerance_pct:'5',min_profit:'',min_margin:'',min_daily_isk_volume:'',
      manufacturing_runs:'1',production_lines:'1',days:'30',sales_tax:'0',buy_broker_fee:'0',sell_broker_fee:'0',facility_tax:'0',system_cost_index:'0',
      min_product_volume:'',include_invention_cost:false,fresh_only:false,require_full_run_demand:false,
      rank_by:'profit_per_day',limit:'25'};},
    async init() {
      this.form = this.defaults();
      this.profiles=this.readBrowserProfiles();
      const restored=this.restoreSettings();
      this.$watch('hiddenColumns', () => this.saveSettings());
      this.$watch('form', () => this.saveSettings());
      this.$watch('filtersOpen', () => this.saveSettings());
      this.$watch('blueprint',()=>this.saveSettings());
      window.addEventListener('pagehide', () => this.saveSettings());
      const initialForm=JSON.stringify(this.form);
      if (!this.demo) {
        try {
          const result = await this.api('/api/v1/profiles'); this.profiles = [...this.profiles,...result.items];
          if (restored) {
            if(!this.profiles.some(p=>p.id===this.profileId))this.profileId='';
          } else if(!this.calculator&&JSON.stringify(this.form)===initialForm) {
            const chosen = this.profiles.find(p => p.is_default);
            if (chosen) {this.profileId=chosen.id; this.setProfile(chosen);}
          }
        } catch (_) { this.profileWarning='Server profiles could not be loaded. Browser profiles and custom filters are still available.'; }
      }
      if(!this.calculator||this.blueprint.type_id)await this.load();
    },
    storageKey() {return 'eve-manufacturing.settings.v1.'+(this.calculator?'calculator.':'')+(this.demo?'demo':'live');},
    restoreSettings() {
      try {
        const saved=JSON.parse(localStorage.getItem(this.storageKey()));
        if(saved?.version!==1 || !saved.form || typeof saved.form!=='object' || Array.isArray(saved.form))return;
        const form=this.defaults();
        this.migrateBrokerSettings(saved.form);
        for(const [key,value] of Object.entries(saved.form)) {
          if(!(key in form))continue;
          if(typeof form[key]==='boolean' ? typeof value!=='boolean' : !['string','number'].includes(typeof value))return;
          form[key]=value;
        }
        if(saved.form.rigs==='true')form.category='Rigs';
        else if(form.category==='Ship and Module Modifications')form.category='Rigs';
        else if(form.category==='Ship Equipment')form.category='Modules';
        this.hiddenColumns=Array.isArray(saved.hiddenColumns)?saved.hiddenColumns.filter(id=>this.columnOptions.some(c=>c.id===id)):[];
        if(this.calculator&&Number.isInteger(Number(saved.blueprint?.type_id))&&Number(saved.blueprint.type_id)>0&&typeof saved.blueprint.name==='string')this.blueprint={type_id:Number(saved.blueprint.type_id),name:saved.blueprint.name};
        this.form=form;
        this.profileSettings=saved.profileSettings && typeof saved.profileSettings==='object' && !Array.isArray(saved.profileSettings)?saved.profileSettings:{};
        this.profileId=typeof saved.profileId==='string'?saved.profileId:'';
        this.filtersOpen=saved.filtersOpen===true;
        this.page.offset=0;
        return true;
      } catch (_) { /* Storage may be unavailable or contain an older invalid value. */ }
    },
    saveSettings() {
      try {
        localStorage.setItem(this.storageKey(),JSON.stringify({version:1,blueprint:this.calculator?this.blueprint:undefined,hiddenColumns:this.hiddenColumns,form:this.form,profileSettings:this.profileSettings,profileId:this.profileId,filtersOpen:this.filtersOpen}));
      } catch (_) { this.storageWarning='Browser storage is unavailable. Changes will work, but may not survive a page reload.'; }
    },
    browserProfilesKey(){return this.storageKey()+'.profiles';},
    readBrowserProfiles(){
      try {
        const values=JSON.parse(localStorage.getItem(this.browserProfilesKey()));
        return Array.isArray(values)?values.filter(p=>p?.browser===true && typeof p.id==='string' && typeof p.name==='string' && p.form && typeof p.form==='object' && !Array.isArray(p.form)):[];
      } catch(_){return [];}
    },
    saveBrowserProfile(){
      this.profileError='';
      const name=this.profileName.trim();
      if(!name || name.length>100){this.profileError='Enter a profile name (1-100 characters).';return;}
      const current=this.profiles.filter(p=>p.browser);
      if(current.some(p=>p.name.toLowerCase()===name.toLowerCase())){this.profileError='A browser profile with this name already exists.';return;}
      const profile={id:'browser:'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)),name,browser:true,form:JSON.parse(JSON.stringify(this.form)),settings:JSON.parse(JSON.stringify(this.profileSettings))};
      try {localStorage.setItem(this.browserProfilesKey(),JSON.stringify([...current,profile]));}
      catch(_){this.profileError='Could not save this profile. Allow browser storage and try again.';return;}
      this.profiles=[profile,...this.profiles];this.profileId=profile.id;this.profileSaveOpen=false;this.profileName='';this.profileNotice='Profile saved in this browser.';this.saveSettings();
    },
    fieldLabel(field){
      const labels={min_profit:'Minimum profit per unit',min_margin:'Minimum margin',min_daily_isk_volume:'Minimum regional turnover',min_product_volume:'Minimum volume at the selected price',days:'History period',sales_tax:'Sales tax',buy_broker_fee:'Buy broker',sell_broker_fee:'Sell broker',facility_tax:'Facility tax',system_cost_index:'System cost index',limit:'Rows per page',hub_id:'Product hub',material_hub_id:'Material purchase hub'};
      return labels[field]||String(field).replaceAll('_',' ').replace(/^./,v=>v.toUpperCase());
    },
    async api(url, options={}) {
      const response = await fetch(url, {credentials:'same-origin',...options,headers:{'X-Requested-With':'XMLHttpRequest',...options.headers}});
      let data; try {data=await response.json();} catch (_) {data=null;}
      if (!response.ok) {
        if (response.status===422 && Array.isArray(data?.detail)) throw new Error(data.detail.map(e => this.fieldLabel(e.loc.at(-1))+': '+e.msg.replace(/^Value error, /,'')).join(' · '));
        if (response.status===401) {location.assign('/login');throw new Error('Your session expired. Please log in again.');}
        throw new Error(typeof data?.detail==='string' ? data.detail : 'Could not load data from the service. Please try again.');
      }
      return data;
    },
    params(form=this.form, settings=this.profileSettings, offset=this.page.offset) {
      const params = new URLSearchParams();
      const values={...this.migrateBrokerSettings({...settings}),...form};
      delete values.invention_science_level; delete values.invention_encryption_level;
      delete values.tech; delete values.category; delete values.rigs;
      delete values.meta_group_ids; delete values.categories; delete values.is_rig;
      if (form.tech === '__profile__') values.meta_group_ids=settings.meta_group_ids;
      else if (form.tech) values.meta_group_ids=[Number(form.tech)];
      if (form.category === '__profile__') {values.categories=settings.categories;values.is_rig=settings.is_rig;}
      else if(form.category==='Rigs')values.is_rig=true;
      else if(form.category==='Modules'){values.categories=['Ship Equipment'];values.is_rig=false;}
      else if(form.category)values.categories=[form.category];
      if(this.calculator){const allowed=['manufacturing_runs','hub_id','material_hub_id','material_order_type','product_order_type','sales_tax','buy_broker_fee','sell_broker_fee','facility_tax','system_cost_index','include_invention_cost','buy_demand_tolerance_pct'];for(const key of Object.keys(values))if(!allowed.includes(key))delete values[key];}
      if(!this.calculator)delete values.manufacturing_runs;
      values.offset=offset;
      for (const [key,value] of Object.entries(values)) {
        if (value===null || value===undefined || value==='') continue;
        if (Array.isArray(value)) value.forEach(v => params.append(key,String(v)));
        else params.set(key,String(value));
      }
      return params;
    },
    migrateBrokerSettings(settings){if(settings.broker_fee!==undefined){settings.buy_broker_fee??=settings.broker_fee;settings.sell_broker_fee??=settings.broker_fee;delete settings.broker_fee;}return settings;},
    setProfile(profile) {
      if(profile.browser)this.migrateBrokerSettings(profile.form);else this.migrateBrokerSettings(profile.settings);
      if(profile.browser){this.form=Object.fromEntries(Object.entries(this.defaults()).map(([key,value])=>[key,profile.form[key]??value]));this.profileSettings=JSON.parse(JSON.stringify(profile.settings||{}));return;}
      const s=profile.settings; this.profileSettings=JSON.parse(JSON.stringify(s));
      this.form={...this.defaults()};
      for (const key of Object.keys(this.form)) if (s[key]!==null && s[key]!==undefined) this.form[key]=s[key];
      this.form.tech=s.meta_group_ids?.length===1?String(s.meta_group_ids[0]):s.meta_group_ids?.length?'__profile__':'';
      this.form.category=s.is_rig===true?'Rigs':s.categories?.length===1?(s.categories[0]==='Ship Equipment'?'Modules':s.categories[0]==='Ship and Module Modifications'?'Rigs':s.categories[0]):s.categories?.length||s.is_rig===false?'__profile__':'';
      this.form.limit=String(s.limit);
    },
    async applyProfile() {
      const profile=this.profiles.find(p=>p.id===this.profileId);
      this.profileNotice='';if(profile) this.setProfile(profile); else {this.profileSettings={};this.form=this.defaults();}
      await this.load(false,0);
    },
    async resetFilters() {this.profileId='';this.profileSettings={};this.form=this.defaults();await this.load(false,0);},
    get resultForm(){return this.appliedForm||this.form;},
    get hasChanges(){return this.appliedForm!==null && (JSON.stringify(this.form)!==JSON.stringify(this.appliedForm)||JSON.stringify(this.profileSettings)!==JSON.stringify(this.appliedSettings)||(this.calculator&&Number(this.blueprint.type_id)!==this.appliedBlueprintId));},
    get selectedProfile(){return this.profiles.find(p=>p.id===this.profileId);},
    async deleteProfile(){
      const profile=this.selectedProfile;if(!profile||this.deletingProfile)return;
      if(profile.browser){this.deleteBrowserProfile();return;}
      if(!confirm('Delete profile "'+profile.name+'"? Current settings will be kept.'))return;
      this.deletingProfile=true;this.error='';
      try{await this.api('/api/v1/profiles/'+encodeURIComponent(profile.id),{method:'DELETE'});
        this.profiles=this.profiles.filter(p=>p.id!==profile.id);
        this.profileId='';this.profileNotice='Profile deleted. Current settings kept.';this.saveSettings();
        try{const result=await this.api('/api/v1/profiles');this.profiles=[...this.profiles.filter(p=>p.browser),...result.items];}catch(_){this.profileWarning='Profile deleted. Reload to refresh the remaining server profiles.';}
      }catch(error){this.error=error.message;}finally{this.deletingProfile=false;}
    },
    get browserProfile(){return this.profiles.find(p=>p.id===this.profileId&&p.browser);},
    updateBrowserProfile(){
      const previous=this.browserProfile;if(!previous)return;
      const replacement={...previous,form:JSON.parse(JSON.stringify(this.form)),settings:JSON.parse(JSON.stringify(this.profileSettings))};
      const next=this.profiles.map(p=>p.id===previous.id?replacement:p);
      try{localStorage.setItem(this.browserProfilesKey(),JSON.stringify(next.filter(p=>p.browser)));}
      catch(_){this.profileError='Could not update this profile. Allow browser storage and retry.';this.profileSaveOpen=true;return;}
      this.profiles=next;this.profileNotice='Profile updated.';this.saveSettings();
    },
    deleteBrowserProfile(){
      const profile=this.browserProfile;if(!profile||!confirm('Delete browser profile "'+profile.name+'"? Current filters will be kept.'))return;
      const next=this.profiles.filter(p=>p.id!==profile.id);
      try{localStorage.setItem(this.browserProfilesKey(),JSON.stringify(next.filter(p=>p.browser)));}
      catch(_){this.profileError='Could not delete this profile. Allow browser storage and retry.';this.profileSaveOpen=true;return;}
      this.profiles=next;this.profileId='';this.profileNotice='Profile deleted. Current filters kept.';this.saveSettings();
    },
    async load(useApplied=false, offset=this.page.offset) {
      if(this.calculator&&!this.blueprint.type_id){this.error='Choose a blueprint from the suggestions.';return;}
      const typeId=this.calculator?Number(useApplied&&this.appliedBlueprintId?this.appliedBlueprintId:this.blueprint.type_id):0;
      this.saveSettings();
      const queryForm=JSON.parse(JSON.stringify(useApplied&&this.appliedForm?this.appliedForm:this.form));
      const querySettings=JSON.parse(JSON.stringify(useApplied&&this.appliedForm?this.appliedSettings:this.profileSettings));
      const seq=++this.requestSequence; this.loading=true; this.error='';
      try {
        let result;
        if(this.demo) result=this.demoPage(queryForm,offset); else result=await this.api((this.calculator?'/api/v1/manufacturing/calculator/'+typeId:'/api/v1/manufacturing/opportunities')+'?'+this.params(queryForm,querySettings,offset));
        if(seq!==this.requestSequence)return;
        this.closeItem();this.page=result;this.appliedForm=queryForm;this.appliedSettings=querySettings;this.appliedBlueprintId=typeId;
        if(this.calculator)await this.loadMaterialNames();else this.loadProgress();
      } catch(error) {if(seq===this.requestSequence){this.error=error.message;}}
      finally {if(seq===this.requestSequence)this.loading=false;}
    },
    invalidateBlueprint(){this.blueprint.type_id='';this.blueprintMatches=[];this.blueprintIndex=-1;this.blueprintOpen=true;this.blueprintSearching=false;this.blueprintSearchDone=false;this.blueprintSequence++;this.requestSequence++;this.loading=false;},
    async searchBlueprint(force=false){const seq=++this.blueprintSequence;const name=this.blueprint.name.trim().replace(/\s+blueprint$/i,'').trim();if(name.length<2||(this.blueprint.type_id&&!force))return;this.blueprintSearching=true;this.blueprintSearchDone=false;try{const params=new URLSearchParams({search:name,limit:50});const data=await this.api('/api/v1/catalog/items?'+params);if(seq===this.blueprintSequence){this.blueprintMatches=data.items;this.blueprintSearchDone=true;this.blueprintIndex=-1;}}catch(error){if(seq===this.blueprintSequence)this.error=error.message;}finally{if(seq===this.blueprintSequence)this.blueprintSearching=false;}},
    chooseBlueprint(item){this.requestSequence++;this.loading=false;this.blueprintSequence++;this.blueprintSearching=false;this.blueprint={type_id:item.type_id,name:item.name+' Blueprint'};this.blueprintOpen=false;this.blueprintIndex=-1;this.error='';this.saveSettings();},
    async reopenBlueprint(){if(this.blueprint.name.trim().length<2)return;this.blueprintOpen=true;if(!this.blueprintSearchDone||!this.blueprintMatches.length)await this.searchBlueprint(true);},
    blueprintKey(event){if(event.key==='Control'){if(!event.repeat)this.reopenBlueprint();return;}if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();this.blueprintOpen=true;if(!this.blueprintMatches.length)return;this.blueprintIndex=event.key==='ArrowDown'?Math.min(this.blueprintMatches.length-1,this.blueprintIndex+1):Math.max(0,this.blueprintIndex-1);this.$nextTick(()=>document.getElementById('calculator-option-'+this.blueprintIndex)?.scrollIntoView({block:'nearest'}));}else if(event.key==='Enter'&&this.blueprintOpen&&this.blueprintMatches.length){event.preventDefault();this.chooseBlueprint(this.blueprintMatches[Math.max(0,this.blueprintIndex)]);}else if(['Escape','Tab'].includes(event.key)){this.blueprintOpen=false;}},
    nextPage(){this.load(true,this.page.offset+this.page.limit);},
    previousPage(){this.load(true,Math.max(0,this.page.offset-this.page.limit));},
    get missingCount(){return (this.page.missing_recipes||0)+(this.page.missing_prices||0)+(this.page.missing_invention||0)+(this.page.missing_job_costs||0);},
    get topDaily(){return this.page.items.length?Math.max(...this.page.items.map(p=>Number(p.rank_profit_per_day))):null;},
    get medianMargin(){const values=this.page.items.map(p=>Number(p.margin_pct)).sort((a,b)=>a-b);if(!values.length)return null;const i=Math.floor(values.length/2);return values.length%2?values[i]:(values[i-1]+values[i])/2;},
    get activeFilters(){return ['search','tech','category','min_profit','min_margin','min_daily_isk_volume','min_product_volume'].filter(k=>this.form[k]!==''&&this.form[k]!==undefined).length+Number(this.form.include_invention_cost)+Number(this.form.fresh_only)+Number(this.form.require_full_run_demand);},
    get rangeLabel(){return this.page.total?`${this.page.offset+1}–${Math.min(this.page.offset+this.page.limit,this.page.total)} of ${this.page.total.toLocaleString('en-US')} opportunities`:'No matching opportunities';},
    hubName(id){return this.hubs.find(h=>h.id===id)?.name||id;},
    money(value){if(value===null||value===undefined)return '—';const n=Number(value);if(!Number.isFinite(n))return '—';return new Intl.NumberFormat('en-US',{notation:Math.abs(n)>=1000000?'compact':'standard',maximumFractionDigits:Math.abs(n)>=1000000||Math.abs(n)<100?2:0}).format(n);},
    percent(value){return Number.isFinite(Number(value))?Number(value).toFixed(1)+'%':'—';},
    closeItem(){const target=this.returnFocus;this.selected=null;this.detailSequence++;this.returnFocus=null;document.body.style.overflow='';this.$nextTick(()=>{if(target?.isConnected&&!this.selected)target.focus();});},
    trapDialog(event){
      const nodes=[...this.$refs.dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),[tabindex="0"]')].filter(n=>n.getClientRects().length);
      const first=nodes[0],last=nodes.at(-1);if(!first){event.preventDefault();return;}
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===this.$refs.dialog)){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===this.$refs.dialog)){event.preventDefault();first.focus();}
    },
    async openItem(item){this.returnFocus=document.activeElement;document.body.style.overflow='hidden';this.selected=item;this.invention=null;this.inventionMessage='';this.inventionChecking=false;this.inventionLoading=false;this.lastInventionCheck=null;this.detailSequence++;await this.$nextTick();await new Promise(resolve=>requestAnimationFrame(resolve));if(this.selected?.type_id!==item.type_id)return;(this.$refs.dialog.querySelector('button:not([disabled])')||this.$refs.dialog).focus();await Promise.allSettled([this.loadHistory(),this.loadMaterialNames(),item.invention_required&&!this.demo?this.loadInvention():Promise.resolve()]);},
    async loadHistory(){
      if(!this.selected)return;
      const seq=this.detailSequence,id=this.selected.type_id;
      this.historyData=null;this.historyError='';this.historyHoverText='';this.historyLoading=true;
      try{
        const data=this.demo?{stale:false,days:Array.from({length:Number(this.resultForm.days)},(_,i)=>({date:new Date(Math.floor(Date.now()/86400000)*86400000-(Number(this.resultForm.days)-i)*86400000).toISOString().slice(0,10),average:String(100000+i*1000+Math.sin(i)*5000),volume:100+i*3}))}:await this.api('/api/v1/market/history/'+id+'?'+new URLSearchParams({hub_id:this.resultForm.hub_id,days:this.resultForm.days}));
        if(seq!==this.detailSequence)return;
        this.historyData={...data,days:[...data.days].sort((a,b)=>a.date.localeCompare(b.date))};
      }catch(_){if(seq===this.detailSequence)this.historyError='Trading history could not be loaded. Your cost calculations are still available.';}
      finally{if(seq===this.detailSequence)this.historyLoading=false;}
    },
    fullMoney(value){if(value===null||value===undefined||!Number.isFinite(Number(value)))return 'Not available';return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(Number(value));},
    materialName(id){return this.materialNames[id]||(this.materialNamesLoading?'Loading name...':'Name unavailable');},
    async loadMaterialNames(){
      const seq=this.detailSequence;
      const ids=[...new Set((this.selected?.materials||(this.calculator?this.page.items[0]?.materials:[])||[]).map(m=>m.type_id))].filter(id=>!this.materialNames[id]);
      this.materialNamesMessage='';
      if(this.demo){this.materialNames={...this.materialNames,34:'Tritanium'};return;}
      if(!ids.length)return;
      this.materialNamesLoading=true;
      try{
        const params=new URLSearchParams();ids.forEach(id=>params.append('type_ids',id));
        const result=await this.api('/api/v1/catalog/names?'+params);
        this.materialNames={...this.materialNames,...result.names};
        if(seq===this.detailSequence&&result.missing_type_ids.length)this.materialNamesMessage='Some material names are unavailable. Quantities and prices are still shown.';
      }catch(_){if(seq===this.detailSequence)this.materialNamesMessage='Material names could not be loaded. Quantities and prices are still shown. Try again.';}
      finally{if(seq===this.detailSequence)this.materialNamesLoading=false;}
    },
    demandTolerance(){const value=this.resultForm.buy_demand_tolerance_pct;return value===undefined||value===null||value===''?5:Number(value);},
    demandWarning(code){return {single_buy_order:'Only one buy order is available. Its removal could eliminate this selling opportunity.',single_buy_order_at_best:'Only one order offers the best buy price. The displayed profit may disappear when it fills.',buy_order_count_unknown:'The number of buy orders is unknown. Check available demand before building.',insufficient_buy_volume_for_one_run:'Buy orders within your selected price range cannot absorb one full production run.'}[code]||'Check the available buy demand before building.';},
    productionLines(){return Number(this.resultForm.production_lines)||1;},
    demandDuration(item){const runs=item.full_runs_at_buy_price,seconds=Number(item.seconds);if(runs===null||runs===undefined||!Number.isFinite(seconds)||seconds<=0)return 'Not available';return this.duration(seconds*Math.ceil(runs/this.productionLines())*(1-0.04*5)*(1-0.03*3));},
    duration(seconds){const n=Number(seconds);if(!Number.isFinite(n)||n<0)return 'Not available';const total=Math.ceil(n),d=Math.floor(total/86400),h=Math.floor(total%86400/3600),m=Math.floor(total%3600/60),s=total%60;return d?(d+'d '+h+'h '+m+'m'):h?(h+'h '+m+'m'):m?(m+'m '+s+'s'):s+'s';},
    inventionStatus(view){
      if(!view?.request)return 'No calculation is prepared for this market and pricing choice. Select Prepare calculation to queue it.';
      const messages={pending:'Queued for background calculation. Select Check status to see when it is ready.',ready:'Calculation ready. Compare the estimated cost per manufactured unit below.',missing_prices:'Some datacore or decryptor prices are missing. Only fully priced alternatives can be compared.',unsupported:'No supported invention route was found for this item.',error:'The last calculation failed. Select Prepare calculation to retry.'};
      return (messages[view.request.status]||'Calculation status is unavailable.')+(view.stale?' This saved valuation is due for its daily update.':'')+(view.request.result&&!view.request.result.complete_pricing?' Some alternatives have missing prices.':'');
    },
    async prepareMarketInvention(){
      if(this.demo||this.preparingMarket)return;
      this.preparingMarket=true;this.preparationMessage='';
      try{await this.api((this.calculator?'/api/v1/invention/'+this.appliedBlueprintId+'/prepare':'/api/v1/invention/prepare')+'?'+this.inventionParams(),{method:'POST'});this.preparationMessage='Invention preparation queued for this material market and pricing choice. Select Show results after the background calculation finishes.';}
      catch(_){this.preparationMessage='Could not request invention preparation. Please try again.';}
      finally{this.preparingMarket=false;}
    },
    inventionParams(){return new URLSearchParams({hub_id:this.resultForm.material_hub_id||this.resultForm.hub_id,order_type:this.resultForm.material_order_type});},
    get inventionReady(){return this.invention?.request?.status==='ready'&&!this.invention.stale;},
    timeLabel(value){if(!value)return 'Not available';const date=new Date(value);return Number.isNaN(date.getTime())?'Not available':new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).format(date);},
    async loadInvention(){
      if(!this.selected||this.demo||this.inventionChecking)return;
      const id=this.selected.type_id,seq=this.detailSequence;
      this.inventionChecking=true;this.inventionMessage='Checking saved calculation...';
      try{
        const data=await this.api(`/api/v1/invention/${id}?${this.inventionParams()}`);
        if(seq!==this.detailSequence||this.selected?.type_id!==id)return;
        this.invention=data;this.lastInventionCheck=new Date().toISOString();this.inventionMessage='Status checked. '+this.inventionStatus(data);
      }catch(_){if(seq===this.detailSequence)this.inventionMessage='Could not check calculation status. Please try again.';}
      finally{if(seq===this.detailSequence)this.inventionChecking=false;}
    },
    async prepareInvention(){
      if(!this.selected||this.demo||this.inventionLoading||this.inventionChecking)return;
      const id=this.selected.type_id,seq=this.detailSequence;
      this.inventionLoading=true;this.inventionMessage='Requesting a background calculation...';
      try{
        const data=await this.api(`/api/v1/invention/${id}/prepare?${this.inventionParams()}`,{method:'POST'});
        if(seq!==this.detailSequence||this.selected?.type_id!==id)return;
        this.invention=data;this.lastInventionCheck=new Date().toISOString();
        this.inventionMessage=data.queued?'Calculation queued. Select Check status to follow its progress.':data.request?.status==='ready'&&!data.stale?'This calculation is already prepared and current. The saved daily result is being reused; no extra job was created.':data.request?.status==='unsupported'?'No supported invention route is available.': 'Preparation is already pending or queued. Select Check status to follow its progress.';
      }catch(_){if(seq===this.detailSequence)this.inventionMessage='Could not request calculation preparation. Please try again.';}
      finally{if(seq===this.detailSequence)this.inventionLoading=false;}
    },
    demoPage(form=this.form,offset=this.page.offset){
      const seeds=[['Damage Control II',2048,2,137000,91000,66.4,9200000,890000000],['Hobgoblin II',2456,2,173000,62000,35.8,6800000,1540000000],['Medium Core Defense Field Extender II',31796,2,820000,244000,29.7,5300000,612000000],['Warrior II',2488,2,206000,73000,35.4,4100000,940000000],['Scourge Heavy Missile',209,1,48,17,35.4,3600000,2640000000],['Gyrostabilizer II',519,2,610000,128000,20.9,2900000,731000000],['Large Shield Extender II',3841,2,936000,164000,17.5,2100000,483000000]];
      let items=seeds.map((s,i)=>({_category:i===2?'Rigs':[1,3].includes(i)?'Drones':i===4?'Ammunition & Charges':'Modules',name:s[0],type_id:s[1],meta_group_id:s[2],total_cost_per_unit:String(s[3]),material_cost_per_unit:String(s[3]*0.96),job_cost_per_unit:String(s[3]*0.04),profit_per_unit:String(s[4]),margin_pct:String(s[5]),rank_profit_per_day:String(s[6]),profit_per_day:String(s[6]*1.2),daily_isk_volume:String(s[7]),units:1,seconds:'7200',revenue_per_unit:String(s[3]+s[4]),invention_required:s[2]===2,invention_included:false,invention_cost_per_unit:'0',sales_tax_per_unit:'0',sales_broker_fee_per_unit:'0',procurement_broker_fee_per_unit:'0',stale:i===5,demand_warnings:i===4?['single_buy_order_at_best']:[],product_volume_at_price:100,full_runs_at_buy_price:100,production_limit_units:100,profit_at_current_buy_price:String(s[4]*100),materials:[{type_id:34,quantity:100,price:String(s[3]*0.96/100),cost:String(s[3]*0.96)}]}));
      if(form.product_order_type!=='buy')items.forEach(i=>{i.profit_at_current_buy_price=null;i.production_limit_units=null;i.full_runs_at_buy_price=null;});
      items=items.filter(i=>(!form.category||form.category==='__profile__'||i._category===form.category)&&(!form.min_daily_isk_volume||Number(i.daily_isk_volume)>=Number(form.min_daily_isk_volume))&&(!form.min_product_volume||i.product_volume_at_price>=Number(form.min_product_volume))&&(!form.search||i.name.toLowerCase().includes(form.search.toLowerCase()))&&(!form.tech||i.meta_group_id===Number(form.tech))&&(!form.min_profit||Number(i.profit_per_unit)>=Number(form.min_profit))&&(!form.min_margin||Number(i.margin_pct)>=Number(form.min_margin))&&(!form.fresh_only||!i.stale));
      if(this.calculator)items=items.filter(item=>item.type_id===Number(this.blueprint.type_id));
      const rank={profit_per_day:'rank_profit_per_day',margin:'margin_pct',profit:'profit_per_unit',demand_profit:'profit_at_current_buy_price'}[form.rank_by];items.sort((a,b)=>(a[rank]===null)-(b[rank]===null)||Number(b[rank])-Number(a[rank])||a.type_id-b.type_id);
      return {items:items.slice(offset,offset+Number(form.limit)),total:items.length,offset:offset,limit:Number(form.limit)};
    }
  }));
});
