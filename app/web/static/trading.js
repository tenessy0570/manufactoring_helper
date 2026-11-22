document.addEventListener('alpine:init',()=>{
  Alpine.data('tradingApp',()=>({
    ...window.marketHistoryChartMethods,
    historyItem:null,historyData:null,historyLoading:false,historyError:'',historyHoverText:'',historyPeriod:30,historySaleSide:'buy',historySequence:0,historyReturnFocus:null,historyOverflow:'',
    profiles:[],profileId:'',profileName:'',profileError:'',profileSaveOpen:false,
    readProfiles(){try{const p=JSON.parse(localStorage.getItem('eve.interhub.profiles.v1'));this.profiles=Array.isArray(p)?p.filter(p=>typeof p.id==='string'&&typeof p.name==='string'&&p.form&&typeof p.form==='object'&&!Array.isArray(p.form)):[];this.profileId=localStorage.getItem('eve.interhub.profile.selected')||'';}catch(_){}},
    persistProfiles(next){try{localStorage.setItem('eve.interhub.profiles.v1',JSON.stringify(next));this.profiles=next;this.profileError='';return true;}catch(_){this.profileError='Could not save profiles. Allow browser storage and retry.';return false;}},
    selectProfile(){const p=this.profiles.find(p=>p.id===this.profileId);if(p){const form=this.defaults();for(const k of Object.keys(form))if(typeof p.form[k]===typeof form[k])form[k]=p.form[k];this.form=form;this.hiddenColumns=Array.isArray(p.hiddenColumns)?p.hiddenColumns.filter(id=>this.columnOptions.some(c=>c.id===id)):[];this.save();}try{localStorage.setItem('eve.interhub.profile.selected',this.profileId);}catch(_){}},
    saveProfile(update=false){const old=this.profiles.find(p=>p.id===this.profileId),name=update?old?.name:this.profileName.trim();if(!name||name.length>100){this.profileError='Enter a profile name (1-100 characters).';return;}if(!update&&this.profiles.some(p=>p.name.toLowerCase()===name.toLowerCase())){this.profileError='A profile with this name already exists.';return;}const p={id:update?old.id:crypto.randomUUID(),name,form:JSON.parse(JSON.stringify(this.form)),hiddenColumns:[...this.hiddenColumns]};if(this.persistProfiles(update?this.profiles.map(v=>v.id===p.id?p:v):[...this.profiles,p])){this.profileId=p.id;this.profileName='';this.profileSaveOpen=false;try{localStorage.setItem('eve.interhub.profile.selected',p.id);}catch(_){}}},
    deleteProfile(){const p=this.profiles.find(p=>p.id===this.profileId);if(p&&confirm('Delete profile '+p.name+'? Current settings will be kept.')&&this.persistProfiles(this.profiles.filter(v=>v.id!==p.id))){this.profileId='';try{localStorage.removeItem('eve.interhub.profile.selected');}catch(_){}}},
    hiddenColumns:[],columnOptions:[{id:'route',label:'Route'},{id:'jumps',label:'Jumps'},{id:'jumpProfit',label:'Profit / jump'},{id:'purchase',label:'Buy / unit'},{id:'sale',label:'Sell / unit'},{id:'profit',label:'Profit / unit'},{id:'density',label:'Profit / m3'},{id:'margin',label:'Margin'},{id:'quantity',label:'Units'},{id:'investment',label:'Required investment'},{id:'cargo',label:'Cargo volume'},{id:'batch',label:'Batch profit'},{id:'turnover',label:'Region turnover / day'},{id:'data',label:'Data freshness'}],
    hubs:['jita','amarr','dodixie','rens','hek'],form:{},applied:null,page:null,loading:false,error:'',storageWarning:'',sequence:0,now:Date.now(),timer:null,
    defaults(){return {filter_daily_turnover:false,price_spikes_only:false,price_spike_threshold:'30',route_mode:'safe',max_jumps:'',min_profit_per_jump:'',source_hub:'',destination_hub:'',purchase_side:'sell',sale_side:'buy',search:'',buy_broker_fee:'0',sell_broker_fee:'0',sales_tax:'0',sell_price_range:'5',buy_price_range:'5',history_days:'30',min_daily_isk_volume:'',min_profit:'',min_margin:'',min_batch_profit:'',max_investment:'',max_cargo_m3:'',max_units:'',fresh_only:false,rank_by:'batch_profit',limit:'25'};},
    async init(){this.form=this.defaults();try{const saved=JSON.parse(localStorage.getItem('eve.interhub.settings.v2')||localStorage.getItem('eve.interhub.settings.v1'));if(saved&&typeof saved==='object'&&!Array.isArray(saved))for(const key of Object.keys(this.form)){const value=saved[key];if(typeof this.form[key]==='boolean'?typeof value==='boolean':['string','number'].includes(typeof value))this.form[key]=value;}if(!localStorage.getItem('eve.interhub.settings.v2')){this.form.source_hub='';this.form.destination_hub='';}}catch(_){}this.readProfiles();this.restoreColumns();this.$watch('hiddenColumns',()=>this.saveColumns());this.$watch('form',()=>this.save());this.timer=setInterval(()=>this.now=Date.now(),30000);await this.load();},
    fullMoney(value){return this.money(value);},
    async openHistory(item){
      if(!this.historyItem){this.historyReturnFocus=document.activeElement;this.historyOverflow=document.body.style.overflow;}
      this.historyItem={...item};this.historyPeriod=Number(this.resultForm.history_days)||30;this.historySaleSide=this.resultForm.sale_side;
      this.historyData=null;this.historyError='';this.historyHoverText='';
      await this.$nextTick();if(!this.$refs.historyDialog.open)this.$refs.historyDialog.showModal();
      document.body.style.overflow='hidden';this.$refs.historyClose.focus();await this.loadHistory();
    },
    closeHistory(){this.historySequence++;if(this.$refs.historyDialog.open)this.$refs.historyDialog.close();this.historyItem=null;this.historyLoading=false;this.historyData=null;document.body.style.overflow=this.historyOverflow;if(this.historyReturnFocus?.isConnected)this.historyReturnFocus.focus();},
    historyOutside(event){if(event.target!==this.$refs.historyDialog)return;const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)this.closeHistory();},
    async loadHistory(){
      if(!this.historyItem)return;const seq=++this.historySequence,item=this.historyItem;
      this.historyLoading=true;this.historyError='';this.historyData=null;this.historyHoverText='';
      try{const params=new URLSearchParams({hub_id:item.destination_hub,days:String(this.historyPeriod)});
        const response=await fetch('/api/v1/market/history/'+item.type_id+'?'+params,{credentials:'same-origin'});
        if(response.status===401){location.assign('/login');throw Error('Session expired.');}
        if(!response.ok)throw Error('Saved trading history could not be loaded.');
        const data=await response.json();if(seq!==this.historySequence)return;
        this.historyData={...data,days:[...data.days].sort((a,b)=>a.date.localeCompare(b.date))};
      }catch(error){if(seq===this.historySequence)this.historyError=error.message;}
      finally{if(seq===this.historySequence)this.historyLoading=false;}
    },
    columnVisible(id){return !this.hiddenColumns.includes(id);},
    restoreColumns(){try{const values=JSON.parse(localStorage.getItem('eve.interhub.columns.v1'));if(Array.isArray(values))this.hiddenColumns=values.filter(id=>this.columnOptions.some(c=>c.id===id));}catch(_){}},
    saveColumns(){try{localStorage.setItem('eve.interhub.columns.v1',JSON.stringify(this.hiddenColumns));}catch(_){this.storageWarning='Column preferences could not be saved in this browser.';}},
    get tableWidth(){return Math.max(320,230+this.columnOptions.filter(c=>this.columnVisible(c.id)).length*100)+'px';},
    compactMoney(value){if(value===null||value===undefined)return '--';return new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(Number(value));},
    destroy(){clearInterval(this.timer);},
    save(){try{localStorage.setItem('eve.interhub.settings.v2',JSON.stringify(this.form));}catch(_){this.storageWarning='Browser storage is unavailable. Settings may not survive a reload.';}},
    get changed(){return this.applied&&JSON.stringify(this.form)!==JSON.stringify(this.applied);},
    get resultForm(){return this.applied||this.form;},
    swap(){const hub=this.form.source_hub;this.form.source_hub=this.form.destination_hub;this.form.destination_hub=hub;},
    money(value){if(value===null||value===undefined)return '--';return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(Number(value));},
    pct(value){return Number(value).toFixed(1)+'%';},
    hubName(hub){return hub?hub.charAt(0).toUpperCase()+hub.slice(1):'All hubs';},
    age(stamp){if(!stamp)return 'not loaded';const m=Math.floor(Math.max(0,this.now-Date.parse(stamp))/60000);return m<1?'<1m':(m>=1440?Math.floor(m/1440)+'d ':'')+Math.floor(m%1440/60)+'h '+m%60+'m';},
    stale(item){return item.stale||[item.source_updated_at,item.destination_updated_at].some(stamp=>Date.parse(stamp)+1200000<=this.now);},
    async load(offset=0,useApplied=false){
      const form=JSON.parse(JSON.stringify(useApplied&&this.applied?this.applied:this.form));
      if(form.source_hub&&form.source_hub===form.destination_hub){this.error='Choose two different hubs.';return;}
      const seq=++this.sequence;this.loading=true;this.error='';this.save();
      try{const params=new URLSearchParams({offset:String(offset)});for(const [key,value] of Object.entries(form))if(value!==''&&value!==null)params.set(key,String(value));
        const response=await fetch('/api/v1/trading/opportunities?'+params,{credentials:'same-origin'});
        if(response.status===401){location.assign('/login');throw Error('Your session expired.');}
        const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map(e=>e.loc.at(-1)+': '+e.msg).join('; '):'Could not load trading opportunities.');
        if(seq!==this.sequence)return;this.page=data;this.applied=form;
      }catch(error){if(seq===this.sequence)this.error=error.message;}finally{if(seq===this.sequence)this.loading=false;}
    }
  }));
});
