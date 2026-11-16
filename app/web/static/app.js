/* Local application state; all monetary calculations remain on the server. */
document.addEventListener('alpine:init', () => {
  Alpine.data('manufacturingApp', () => ({
    demo: new URLSearchParams(location.search).get('demo') === '1', loading: false,
    filtersOpen: false, error: '', profileId: '', profiles: [], profileSettings: {},
    selected: null, invention: null, inventionMessage: '', inventionLoading: false,
    requestSequence: 0, detailSequence: 0,
    hubs: [{id:'jita',name:'Jita'},{id:'amarr',name:'Amarr'},{id:'dodixie',name:'Dodixie'},{id:'rens',name:'Rens'},{id:'hek',name:'Hek'}],
    form: {}, page: {items:[],total:0,offset:0,limit:25},
    defaults() {return {search:'',hub_id:'jita',material_hub_id:'',tech:'',category:'',rigs:'',
      material_order_type:'sell',product_order_type:'sell',min_profit:'',min_margin:'',min_daily_isk_volume:'',
      days:'30',sales_tax:'0',broker_fee:'0',invention_science_level:'5',invention_encryption_level:'4',
      min_product_volume:'',include_invention_cost:false,fresh_only:false,require_full_run_demand:false,
      rank_by:'profit_per_day',limit:'25'};},
    async init() {
      this.form = this.defaults();
      if (!this.demo) {
        try {
          const result = await this.api('/api/v1/profiles'); this.profiles = result.items;
          const chosen = this.profiles.find(p => p.is_default);
          if (chosen) {this.profileId=chosen.id; this.setProfile(chosen);}
        } catch (_) { this.error='Saved profiles could not be loaded. You can still use custom filters.'; }
      }
      await this.load();
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
    params() {
      const params = new URLSearchParams();
      const values={...this.profileSettings,...this.form};
      delete values.tech; delete values.category; delete values.rigs;
      delete values.meta_group_ids; delete values.categories; delete values.is_rig;
      if (this.form.tech === '__profile__') values.meta_group_ids=this.profileSettings.meta_group_ids;
      else if (this.form.tech) values.meta_group_ids=[Number(this.form.tech)];
      if (this.form.category === '__profile__') values.categories=this.profileSettings.categories;
      else if (this.form.category) values.categories=[this.form.category];
      if (this.form.rigs!=='') values.is_rig=this.form.rigs==='true';
      values.offset=this.page.offset;
      for (const [key,value] of Object.entries(values)) {
        if (value===null || value===undefined || value==='') continue;
        if (Array.isArray(value)) value.forEach(v => params.append(key,String(v)));
        else params.set(key,String(value));
      }
      return params;
    },
    setProfile(profile) {
      const s=profile.settings; this.profileSettings=structuredClone(s);
      this.form={...this.defaults()};
      for (const key of Object.keys(this.form)) if (s[key]!==null && s[key]!==undefined) this.form[key]=s[key];
      this.form.tech=s.meta_group_ids?.length===1?String(s.meta_group_ids[0]):s.meta_group_ids?.length?'__profile__':'';
      this.form.category=s.categories?.length===1?s.categories[0]:s.categories?.length?'__profile__':'';
      this.form.rigs=s.is_rig===null||s.is_rig===undefined?'':String(s.is_rig);
      this.form.limit=String(s.limit); this.page.offset=0;
    },
    async applyProfile() {
      const profile=this.profiles.find(p=>p.id===this.profileId);
      if(profile) this.setProfile(profile); else {this.profileSettings={};this.form=this.defaults();this.page.offset=0;}
      await this.load();
    },
    async resetFilters() {this.profileId='';this.profileSettings={};this.form=this.defaults();this.page.offset=0;await this.load();},
    async load() {
      const seq=++this.requestSequence; this.loading=true; this.error='';
      try {
        let result;
        if(this.demo) result=this.demoPage(); else result=await this.api('/api/v1/manufacturing/opportunities?'+this.params());
        if(seq!==this.requestSequence)return;
        this.page=result;
      } catch(error) {if(seq===this.requestSequence){this.error=error.message;this.page={items:[],total:0,offset:0,limit:Number(this.form.limit)};}}
      finally {if(seq===this.requestSequence)this.loading=false;}
    },
    nextPage(){this.page.offset+=this.page.limit;this.load();},
    previousPage(){this.page.offset=Math.max(0,this.page.offset-this.page.limit);this.load();},
    get missingCount(){return (this.page.missing_recipes||0)+(this.page.missing_prices||0)+(this.page.missing_invention||0);},
    get topDaily(){return this.page.items.length?Math.max(...this.page.items.map(p=>Number(p.rank_profit_per_day))):null;},
    get medianMargin(){const values=this.page.items.map(p=>Number(p.margin_pct)).sort((a,b)=>a-b);if(!values.length)return null;const i=Math.floor(values.length/2);return values.length%2?values[i]:(values[i-1]+values[i])/2;},
    get activeFilters(){return ['search','tech','category','rigs','min_profit','min_margin','min_daily_isk_volume','min_product_volume'].filter(k=>this.form[k]!==''&&this.form[k]!==undefined).length+Number(this.form.include_invention_cost)+Number(this.form.fresh_only)+Number(this.form.require_full_run_demand);},
    get rangeLabel(){return this.page.total?`${this.page.offset+1}–${Math.min(this.page.offset+this.page.limit,this.page.total)} of ${this.page.total.toLocaleString('en-US')} opportunities`:'No matching opportunities';},
    hubName(id){return this.hubs.find(h=>h.id===id)?.name||id;},
    money(value){if(value===null||value===undefined)return '—';const n=Number(value);if(!Number.isFinite(n))return '—';return new Intl.NumberFormat('en-US',{notation:Math.abs(n)>=1000000?'compact':'standard',maximumFractionDigits:Math.abs(n)>=1000000?2:0}).format(n);},
    percent(value){return Number.isFinite(Number(value))?Number(value).toFixed(1)+'%':'—';},
    async openItem(item){this.selected=item;this.invention=null;this.inventionMessage='';this.detailSequence++;await this.$nextTick();this.$refs.dialog.focus();if(item.invention_required&&!this.demo) await this.loadInvention();},
    inventionParams(){return new URLSearchParams({hub_id:this.form.material_hub_id||this.form.hub_id,order_type:this.form.material_order_type,science_level:this.form.invention_science_level,encryption_level:this.form.invention_encryption_level,broker_fee:this.form.broker_fee});},
    async loadInvention(){const id=this.selected?.type_id, seq=this.detailSequence;try{const data=await this.api(`/api/v1/invention/${id}?${this.inventionParams()}`);if(seq!==this.detailSequence||this.selected?.type_id!==id)return;this.invention=data;this.inventionMessage=!data.request?'Not prepared for these settings yet. Prepare a cached calculation to compare decryptors.':`${data.request.status.replaceAll('_',' ')}${data.stale?' · stale':''}${data.request.result&&!data.request.result.complete_pricing?' · some price options are missing':''}`;}catch(e){if(this.selected?.type_id===id)this.inventionMessage=e.message;}},
    async prepareInvention(){if(!this.selected||this.demo)return;const id=this.selected.type_id;this.inventionLoading=true;try{await this.api(`/api/v1/invention/${id}/prepare?${this.inventionParams()}`,{method:'POST'});if(this.selected?.type_id===id){await this.loadInvention();this.inventionMessage='Preparation requested. The worker will calculate and cache this result. Reopen these details or refresh to check progress.';}}catch(e){this.inventionMessage=e.message;}finally{this.inventionLoading=false;}},
    demoPage(){
      const seeds=[['Damage Control II',2048,2,137000,91000,66.4,9200000,890000000],['Hobgoblin II',2456,2,173000,62000,35.8,6800000,1540000000],['Medium Core Defense Field Extender I',31796,1,820000,244000,29.7,5300000,612000000],['Warrior II',2488,2,206000,73000,35.4,4100000,940000000],['Scourge Heavy Missile',209,1,48,17,35.4,3600000,2640000000],['Gyrostabilizer II',519,2,610000,128000,20.9,2900000,731000000],['Large Shield Extender II',3841,2,936000,164000,17.5,2100000,483000000]];
      let items=seeds.map((s,i)=>({name:s[0],type_id:s[1],meta_group_id:s[2],total_cost_per_unit:String(s[3]),material_cost_per_unit:String(s[3]*0.96),job_cost_per_unit:String(s[3]*0.04),profit_per_unit:String(s[4]),margin_pct:String(s[5]),rank_profit_per_day:String(s[6]),profit_per_day:String(s[6]*1.2),daily_isk_volume:String(s[7]),units:1,seconds:'7200',revenue_per_unit:String(s[3]+s[4]),invention_required:s[2]===2,invention_included:false,invention_cost_per_unit:'0',sales_tax_per_unit:'0',sales_broker_fee_per_unit:'0',procurement_broker_fee_per_unit:'0',stale:i===5,demand_warnings:i===4?['single_buy_order_at_best']:[],product_volume_at_price:100,full_runs_at_buy_price:100,production_limit_units:100,profit_at_current_buy_price:String(s[4]*100),materials:[{type_id:34,quantity:100,price:String(s[3]*0.96/100),cost:String(s[3]*0.96)}]}));
      items=items.filter(i=>(!this.form.search||i.name.toLowerCase().includes(this.form.search.toLowerCase()))&&(!this.form.tech||i.meta_group_id===Number(this.form.tech))&&(!this.form.min_profit||Number(i.profit_per_unit)>=Number(this.form.min_profit))&&(!this.form.min_margin||Number(i.margin_pct)>=Number(this.form.min_margin))&&(!this.form.fresh_only||!i.stale));
      const rank={profit_per_day:'rank_profit_per_day',margin:'margin_pct',profit:'profit_per_unit'}[this.form.rank_by];items.sort((a,b)=>Number(b[rank])-Number(a[rank]));
      return {items:items.slice(this.page.offset,this.page.offset+Number(this.form.limit)),total:items.length,offset:this.page.offset,limit:Number(this.form.limit)};
    }
  }));
});
