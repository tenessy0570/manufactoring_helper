window.marketHistoryChartMethods={
    chartMoney(value){return new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(Number(value));},
    historyChart(metric){
      const days=(this.historyData?.days||[]).filter(d=>Number.isFinite(Number(d[metric])));
      if(!days.length)return {path:'',min:0,max:0,first:'',last:''};
      const values=days.map(d=>Number(d[metric])),low=metric==='volume'?0:Math.min(...values),high=Math.max(...values),padding=metric==='volume'?0:Math.max((high-low)*0.05,high*0.01,1),min=Math.max(0,low-padding),max=Math.max(min+1,high+padding);
      const first=Date.parse(days[0].date),last=Date.parse(days.at(-1).date),span=Math.max(86400000,last-first);
      let previous=null;
      const path=days.map((d,index)=>{const time=Date.parse(d.date),x=last===first?300:10+(time-first)/span*580,y=150-(Number(d[metric])-min)/(max-min)*140;
        if(metric==='volume'){const w=Math.max(1,Math.min(12,580/(span/86400000+1)*0.7));return 'M'+(x-w/2)+',150V'+y+'h'+w+'V150Z';}
        const isolated=(index===0||time-Date.parse(days[index-1].date)>86400000)&&(index===days.length-1||Date.parse(days[index+1].date)-time>86400000);
        if(isolated){previous=time;return 'M'+(x-3)+','+y+'h6';}
        const command=previous===null||time-previous>86400000?'M':'L';previous=time;return command+x+','+y;
      }).join(' ');
      return {path,min,max,first:days[0].date,last:days.at(-1).date};
    },
    inspectHistory(event){
      const days=this.historyData?.days||[];if(!days.length)return;
      const rect=event.currentTarget.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),first=Date.parse(days[0].date),last=Date.parse(days.at(-1).date),target=first+(last-first)*ratio;
      const day=days.reduce((a,b)=>Math.abs(Date.parse(a.date)-target)<Math.abs(Date.parse(b.date)-target)?a:b);
      this.historyHoverText=day.date+' | '+this.fullMoney(day.average)+' ISK average | '+Number(day.volume).toLocaleString('en-US')+' units traded';
    },
};
