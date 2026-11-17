document.addEventListener('alpine:init',()=>{
  Alpine.data('shoppingApp',()=>({
    showBuyList:false,suggestionsOpen:false,activeMatch:-1,hub:'jita',searchText:'',matches:[],typeId:'',units:'1',result:null,names:{},error:'',message:'',busy:false,searching:false,searchSequence:0,
    async api(url,options={}){const response=await fetch(url,{credentials:'same-origin',...options,headers:{'X-Requested-With':'XMLHttpRequest',...options.headers}});if(response.status===401){location.assign('/login');throw Error('Please log in again.');}const data=await response.json();if(!response.ok)throw new Error(response.status===422?'Enter a whole unit quantity between 1 and 1,000,000,000.':'Could not load data. Please retry.');return data;},
    async search(){if(this.typeId)return;const seq=++this.searchSequence;this.typeId='';this.result=null;this.error='';const name=this.searchText.trim().replace(/\s+blueprint$/i,'').trim();this.matches=[];if(name.length<2){this.searching=false;return;}this.searching=true;try{const data=await this.api('/api/v1/catalog/items?'+new URLSearchParams({search:name,meta_group_ids:'2',limit:50}));if(seq===this.searchSequence){this.matches=data.items;this.activeMatch=-1;}}catch(error){if(seq===this.searchSequence)this.error=error.message;}finally{if(seq===this.searchSequence)this.searching=false;}},
    invalidateSearch(){this.typeId='';this.result=null;this.matches=[];this.activeMatch=-1;this.suggestionsOpen=true;this.searchSequence++;},
    chooseBlueprint(item){this.searchSequence++;this.typeId=String(item.type_id);this.searchText=item.name+' Blueprint';this.suggestionsOpen=false;this.activeMatch=-1;this.result=null;this.error='';this.message='';this.$refs.blueprintSearch.focus();this.suggestionsOpen=false;},
    searchKey(event){
      if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();this.suggestionsOpen=true;if(!this.matches.length)return;this.activeMatch=event.key==='ArrowDown'?Math.min(this.matches.length-1,this.activeMatch+1):Math.max(0,this.activeMatch-1);this.$nextTick(()=>document.getElementById('blueprint-option-'+this.activeMatch)?.scrollIntoView({block:'nearest'}));}
      else if(event.key==='Enter'&&this.suggestionsOpen&&this.matches.length){event.preventDefault();this.chooseBlueprint(this.matches[this.activeMatch<0?0:this.activeMatch]);}
      else if(event.key==='Escape'){event.preventDefault();this.suggestionsOpen=false;}
      else if(event.key==='Tab')this.suggestionsOpen=false;
    },
    get selected(){return this.result?.best;},
    name(id){return this.names[id]||'Name unavailable';},
    async calculate(){if(!this.typeId){this.error='Select a matching T2 blueprint.';return;}this.busy=true;this.error='';this.message='';this.result=null;try{const id=this.typeId,units=this.units;const result=await this.api('/api/v1/invention/shopping/'+id+'?'+new URLSearchParams({units,hub_id:this.hub}));if(id!==this.typeId||units!==this.units)return;this.result=result;const ids=[...new Set(result.options.flatMap(o=>[o.source_blueprint_id,...o.materials.map(m=>m.type_id)]))];if(ids.length){try{const params=new URLSearchParams();ids.forEach(id=>params.append('type_ids',id));const data=await this.api('/api/v1/catalog/names?'+params);this.names={...this.names,...data.names};if(data.missing_type_ids.length)this.message='Some item names are unavailable. Retry to resolve them.';}catch(_){this.message='Item names are unavailable. Retry calculation to load them.';}}}catch(error){this.error=error.message;}finally{this.busy=false;}},
    get buyListText(){return (this.selected?.materials||[]).map(m=>this.names[m.type_id]+'\t'+m.quantity).join('\n');},
    get canCopyBuyList(){return !!this.selected&&this.selected.materials.every(m=>!!this.names[m.type_id]);},
    async copyBuyList(){
      if(!this.canCopyBuyList){this.message='Wait for item names before copying.';return;}
      const text=this.buyListText;
      try{await navigator.clipboard.writeText(text);this.message='Buy list copied. Paste it into EVE Multibuy (Ctrl+V).';}
      catch(_){const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();this.message=copied?'Buy list copied. Paste it into EVE Multibuy (Ctrl+V).':'Clipboard unavailable. Select and copy the list below.';if(!copied)this.showBuyList=true;}
    },
    async prepare(){if(!this.typeId||this.busy)return;this.busy=true;this.error='';try{await this.api('/api/v1/invention/'+this.typeId+'/prepare',{method:'POST'});this.message='Preparation requested using the shared invention cache. Select Check status shortly. No separate skill cache is created.';}catch(error){this.error=error.message;}finally{this.busy=false;}},
  }));
});
