document.addEventListener('alpine:init',()=>{Alpine.data('cargoApp',()=>({
...window.marketHistoryChartMethods,
 historyItem:null,historyData:null,historyLoading:false,historyError:'',historyHoverText:'',historyPeriod:30,historySaleSide:'buy',historySequence:0,historyReturnFocus:null,historyOverflow:'',
 hubName(h){return this.name(h);},
    fullMoney(value){return this.money(value);},
    async openHistory(item,plan){
      item={...item,destination_hub:plan.destination_hub};
      if(!this.historyItem){this.historyReturnFocus=document.activeElement;this.historyOverflow=document.body.style.overflow;}
      this.historyItem={...item};this.historyPeriod=Number(30)||30;this.historySaleSide=this.applied.sale_side;
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

form:{filter_daily_turnover:false,min_daily_isk_volume:'',history_days:'30',sale_side:'buy',source_hub:'jita',destination_hub:'',cargo_m3:'',budget:'',sales_tax:'0',sell_price_range:'5',buy_price_range:'5',route_mode:'safe',fresh_only:false},hubs:['jita','amarr','dodixie','rens','hek'],result:null,loading:false,error:'',applied:null,
init(){try{const saved=JSON.parse(localStorage.getItem('eve.cargo.settings.v1'));if(saved)for(const key of Object.keys(this.form))if(typeof saved[key]===typeof this.form[key])this.form[key]=saved[key];}catch(_){}this.$watch('form',()=>this.saveSettings());},
saveSettings(){try{localStorage.setItem('eve.cargo.settings.v1',JSON.stringify(this.form));}catch(_){this.error='Settings could not be saved in this browser.';}},
name(h){return h?h[0].toUpperCase()+h.slice(1):'Best destination';},compact(v){return new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(Number(v));},money(v){return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(Number(v));},
get changed(){return this.applied&&JSON.stringify(this.form)!==JSON.stringify(this.applied);},
async calculate(){if(this.loading)return;this.loading=true;this.error='';const form={...this.form};try{const body={...form,cargo_m3:form.cargo_m3};if(!body.destination_hub)delete body.destination_hub;if(!body.budget)delete body.budget;if(body.min_daily_isk_volume==='')delete body.min_daily_isk_volume;const r=await fetch('/api/v1/trading/cargo',{method:'POST',signal:AbortSignal.timeout(90000),credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify(body)});if(r.status===401){location.assign('/login');return;}const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Check the hubs, cargo capacity and numeric settings.');this.result=data;this.applied=form;this.saveSettings(); }catch(e){this.error=e.message;}finally{this.loading=false;}}
}));});