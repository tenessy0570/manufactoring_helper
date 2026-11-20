document.addEventListener('alpine:init',()=>{
  Alpine.data('freshnessHeader',()=>({
    hub:'jita',sources:[],error:false,loading:false,now:Date.now(),sequence:0,timer:null,
    labels:{market:'Market',history:'History',recipes:'Recipes',invention:'Invention'},
    async init(){try{const hub=localStorage.getItem('eve.freshness.hub');if(['jita','amarr','dodixie','rens','hek'].includes(hub))this.hub=hub;}catch(_){}await this.refresh();this.timer=setInterval(()=>{this.now=Date.now();if(!document.hidden)this.refresh();},60000);},
    destroy(){clearInterval(this.timer);},
    async refresh(){const sequence=++this.sequence;this.loading=true;try{const response=await fetch('/health/freshness?hub='+this.hub,{credentials:'same-origin'});if(!response.ok)throw Error('unavailable');const data=await response.json();if(sequence!==this.sequence)return;this.sources=data.sources||[];this.error=false;}catch(_){if(sequence===this.sequence)this.error=true;}finally{if(sequence===this.sequence)this.loading=false;}},
    changeHub(){try{localStorage.setItem('eve.freshness.hub',this.hub);}catch(_){}this.sources=[];this.refresh();},
    age(stamp){if(!stamp)return 'no data';const minutes=Math.floor(Math.max(0,this.now-Date.parse(stamp))/60000);return minutes<1?'<1m':(minutes>=1440?Math.floor(minutes/1440)+'d ':'')+Math.floor(minutes%1440/60)+'h '+minutes%60+'m';},
    percentage(source){return source.cached>0?new Intl.NumberFormat('en-US',{maximumFractionDigits:1}).format(Math.floor(source.fresh*1000/source.cached)/10)+'%':'--';},
    text(source){return this.labels[source.source]+': '+(source.status==='missing'?'no data':this.age(source.oldest_at))+(source.status==='partial'?' (partial)':source.status==='stale'?' (due)':'');},
    detail(source){return this.labels[source.source]+': '+source.fresh+' of '+source.cached+' saved entries fresh. Oldest: '+this.age(source.oldest_at)+', latest: '+this.age(source.newest_at)+'. Cached entries only; this is not full catalogue coverage.';}
  }));
});
