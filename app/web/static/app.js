/* Local application state; all monetary calculations remain on the server. */
document.addEventListener('alpine:init', () => {
  Alpine.data('manufacturingApp', () => ({
    demo: new URLSearchParams(location.search).get('demo') === '1', loading: false,
    filtersOpen: true, error: '', profileId: '', profiles: [], profileSettings: {},
    profileSaveOpen:false,profileName:'',profileError:'',profileWarning:'',storageWarning:'',
    selected: null, invention: null, inventionMessage: '', inventionLoading: false,
    requestSequence: 0, detailSequence: 0, appliedForm:null, appliedSettings:{}, returnFocus:null, profileNotice:'',
    hubs: [{id:'jita',name:'Jita'},{id:'amarr',name:'Amarr'},{id:'dodixie',name:'Dodixie'},{id:'rens',name:'Rens'},{id:'hek',name:'Hek'}],
    form: {}, page: {items:[],total:0,offset:0,limit:25},
    defaults() {return {search:'',hub_id:'jita',material_hub_id:'',tech:'',category:'',
      material_order_type:'sell',product_order_type:'sell',min_profit:'',min_margin:'',min_daily_isk_volume:'',
      days:'30',sales_tax:'0',broker_fee:'0',invention_science_level:'5',invention_encryption_level:'4',
      min_product_volume:'',include_invention_cost:false,fresh_only:false,require_full_run_demand:false,
      rank_by:'profit_per_day',limit:'25'};},
    async init() {
      this.form = this.defaults();
      this.profiles=this.readBrowserProfiles();
      const restored=this.restoreSettings();
      this.$watch('form', () => this.saveSettings());
      this.$watch('filtersOpen', () => this.saveSettings());
      window.addEventListener('pagehide', () => this.saveSettings());
      const initialForm=JSON.stringify(this.form);
      if (!this.demo) {
        try {
          const result = await this.api('/api/v1/profiles'); this.profiles = [...this.profiles,...result.items];
          if (restored) {
            if(!this.profiles.some(p=>p.id===this.profileId))this.profileId='';
          } else if(JSON.stringify(this.form)===initialForm) {
            const chosen = this.profiles.find(p => p.is_default);
            if (chosen) {this.profileId=chosen.id; this.setProfile(chosen);}
          }
        } catch (_) { this.profileWarning='Server profiles could not be loaded. Browser profiles and custom filters are still available.'; }
      }
      await this.load();
    },
    storageKey() {return 'eve-manufacturing.settings.v1.'+(this.demo?'demo':'live');},
    restoreSettings() {
      try {
        const saved=JSON.parse(localStorage.getItem(this.storageKey()));
        if(saved?.version!==1 || !saved.form || typeof saved.form!=='object' || Array.isArray(saved.form))return;
        const form=this.defaults();
        for(const [key,value] of Object.entries(saved.form)) {
          if(!(key in form))continue;
          if(typeof form[key]==='boolean' ? typeof value!=='boolean' : !['string','number'].includes(typeof value))return;
          form[key]=value;
        }
        if(saved.form.rigs==='true')form.category='Rigs';
        else if(form.category==='Ship and Module Modifications')form.category='Rigs';
        else if(form.category==='Ship Equipment')form.category='Modules';
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
        localStorage.setItem(this.storageKey(),JSON.stringify({version:1,form:this.form,profileSettings:this.profileSettings,profileId:this.profileId,filtersOpen:this.filtersOpen}));
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
    async api(url, options={}) {
      const response = await fetch(url, {credentials:'same-origin',...options});
      let data; try {data=await response.json();} catch (_) {data=null;}
      if (!response.ok) {
        if (response.status===422 && Array.isArray(data?.detail)) throw new Error(data.detail.map(e => e.loc.slice(1).join('.')+': '+e.msg).join(' · '));
        if (response.status===401) throw new Error('Authentication required. Sign in and retry.');
        throw new Error(typeof data?.detail==='string' ? data.detail : 'Could not load market data. Check that the database and workers are running, then retry.');
      }
      return data;
    },
    params(form=this.form, settings=this.profileSettings, offset=this.page.offset) {
      const params = new URLSearchParams();
      const values={...settings,...form};
      delete values.tech; delete values.category; delete values.rigs;
      delete values.meta_group_ids; delete values.categories; delete values.is_rig;
      if (form.tech === '__profile__') values.meta_group_ids=settings.meta_group_ids;
      else if (form.tech) values.meta_group_ids=[Number(form.tech)];
      if (form.category === '__profile__') {values.categories=settings.categories;values.is_rig=settings.is_rig;}
      else if(form.category==='Rigs')values.is_rig=true;
      else if(form.category==='Modules'){values.categories=['Ship Equipment'];values.is_rig=false;}
      else if(form.category)values.categories=[form.category];
      values.offset=offset;
      for (const [key,value] of Object.entries(values)) {
        if (value===null || value===undefined || value==='') continue;
        if (Array.isArray(value)) value.forEach(v => params.append(key,String(v)));
        else params.set(key,String(value));
      }
      return params;
    },
    setProfile(profile) {
      if(profile.browser){this.form={...this.defaults(),...JSON.parse(JSON.stringify(profile.form))};this.profileSettings=JSON.parse(JSON.stringify(profile.settings||{}));return;}
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
    get hasChanges(){return this.appliedForm!==null && (JSON.stringify(this.form)!==JSON.stringify(this.appliedForm)||JSON.stringify(this.profileSettings)!==JSON.stringify(this.appliedSettings));},
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
      this.saveSettings();
      const queryForm=JSON.parse(JSON.stringify(useApplied&&this.appliedForm?this.appliedForm:this.form));
      const querySettings=JSON.parse(JSON.stringify(useApplied&&this.appliedForm?this.appliedSettings:this.profileSettings));
      const seq=++this.requestSequence; this.loading=true; this.error='';
      try {
        let result;
        if(this.demo) result=this.demoPage(queryForm,offset); else result=await this.api('/api/v1/manufacturing/opportunities?'+this.params(queryForm,querySettings,offset));
        if(seq!==this.requestSequence)return;
        this.closeItem();this.page=result;this.appliedForm=queryForm;this.appliedSettings=querySettings;
      } catch(error) {if(seq===this.requestSequence){this.error=error.message;}}
      finally {if(seq===this.requestSequence)this.loading=false;}
    },
    nextPage(){this.load(true,this.page.offset+this.page.limit);},
    previousPage(){this.load(true,Math.max(0,this.page.offset-this.page.limit));},
    get missingCount(){return (this.page.missing_recipes||0)+(this.page.missing_prices||0)+(this.page.missing_invention||0);},
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
    async openItem(item){this.returnFocus=document.activeElement;document.body.style.overflow='hidden';this.selected=item;this.invention=null;this.inventionMessage='';this.detailSequence++;await this.$nextTick();await new Promise(resolve=>requestAnimationFrame(resolve));if(this.selected?.type_id!==item.type_id)return;(this.$refs.dialog.querySelector('button:not([disabled])')||this.$refs.dialog).focus();if(item.invention_required&&!this.demo) await this.loadInvention();},
    inventionParams(){return new URLSearchParams({hub_id:this.resultForm.material_hub_id||this.resultForm.hub_id,order_type:this.resultForm.material_order_type,science_level:this.resultForm.invention_science_level,encryption_level:this.resultForm.invention_encryption_level,broker_fee:this.resultForm.broker_fee});},
    async loadInvention(){const id=this.selected?.type_id, seq=this.detailSequence;try{const data=await this.api(`/api/v1/invention/${id}?${this.inventionParams()}`);if(seq!==this.detailSequence||this.selected?.type_id!==id)return;this.invention=data;this.inventionMessage=!data.request?'Not prepared for these settings yet. Prepare a cached calculation to compare decryptors.':`${data.request.status.replaceAll('_',' ')}${data.stale?' · stale':''}${data.request.result&&!data.request.result.complete_pricing?' · some price options are missing':''}`;}catch(e){if(seq===this.detailSequence&&this.selected?.type_id===id)this.inventionMessage=e.message;}},
    async prepareInvention(){if(!this.selected||this.demo)return;const id=this.selected.type_id;this.inventionLoading=true;try{await this.api(`/api/v1/invention/${id}/prepare?${this.inventionParams()}`,{method:'POST'});if(this.selected?.type_id===id){await this.loadInvention();this.inventionMessage='Preparation requested. The worker will calculate and cache this result. Reopen these details or refresh to check progress.';}}catch(e){this.inventionMessage=e.message;}finally{this.inventionLoading=false;}},
    demoPage(form=this.form,offset=this.page.offset){
      const seeds=[['Damage Control II',2048,2,137000,91000,66.4,9200000,890000000],['Hobgoblin II',2456,2,173000,62000,35.8,6800000,1540000000],['Medium Core Defense Field Extender II',31796,2,820000,244000,29.7,5300000,612000000],['Warrior II',2488,2,206000,73000,35.4,4100000,940000000],['Scourge Heavy Missile',209,1,48,17,35.4,3600000,2640000000],['Gyrostabilizer II',519,2,610000,128000,20.9,2900000,731000000],['Large Shield Extender II',3841,2,936000,164000,17.5,2100000,483000000]];
      let items=seeds.map((s,i)=>({_category:i===2?'Rigs':[1,3].includes(i)?'Drones':i===4?'Ammunition & Charges':'Modules',name:s[0],type_id:s[1],meta_group_id:s[2],total_cost_per_unit:String(s[3]),material_cost_per_unit:String(s[3]*0.96),job_cost_per_unit:String(s[3]*0.04),profit_per_unit:String(s[4]),margin_pct:String(s[5]),rank_profit_per_day:String(s[6]),profit_per_day:String(s[6]*1.2),daily_isk_volume:String(s[7]),units:1,seconds:'7200',revenue_per_unit:String(s[3]+s[4]),invention_required:s[2]===2,invention_included:false,invention_cost_per_unit:'0',sales_tax_per_unit:'0',sales_broker_fee_per_unit:'0',procurement_broker_fee_per_unit:'0',stale:i===5,demand_warnings:i===4?['single_buy_order_at_best']:[],product_volume_at_price:100,full_runs_at_buy_price:100,production_limit_units:100,profit_at_current_buy_price:String(s[4]*100),materials:[{type_id:34,quantity:100,price:String(s[3]*0.96/100),cost:String(s[3]*0.96)}]}));
      items=items.filter(i=>(!form.category||form.category==='__profile__'||i._category===form.category)&&(!form.min_daily_isk_volume||Number(i.daily_isk_volume)>=Number(form.min_daily_isk_volume))&&(!form.min_product_volume||i.product_volume_at_price>=Number(form.min_product_volume))&&(!form.search||i.name.toLowerCase().includes(form.search.toLowerCase()))&&(!form.tech||i.meta_group_id===Number(form.tech))&&(!form.min_profit||Number(i.profit_per_unit)>=Number(form.min_profit))&&(!form.min_margin||Number(i.margin_pct)>=Number(form.min_margin))&&(!form.fresh_only||!i.stale));
      const rank={profit_per_day:'rank_profit_per_day',margin:'margin_pct',profit:'profit_per_unit'}[form.rank_by];items.sort((a,b)=>Number(b[rank])-Number(a[rank]));
      return {items:items.slice(offset,offset+Number(form.limit)),total:items.length,offset:offset,limit:Number(form.limit)};
    }
  }));
});
