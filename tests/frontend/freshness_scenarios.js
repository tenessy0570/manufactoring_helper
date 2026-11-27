async function checkFreshnessHeader(){
  const header=document.querySelector('.freshness-header'),a=Alpine.$data(header),original=window.fetch;
  const stored=localStorage.getItem('eve.freshness.hub');let failed=false;
  window.fetch=async url=>{
    if(!String(url).startsWith('/health/freshness?'))return original(url);
    if(failed)return new Response('{}',{status:503});
    return new Response(JSON.stringify({sources:[{source:'market',cached:1,fresh:1,status:'fresh',oldest_at:new Date(Date.now()-600000).toISOString(),newest_at:new Date().toISOString()},{source:'history',cached:2,fresh:1,status:'partial',oldest_at:new Date(Date.now()-90000000).toISOString(),newest_at:new Date().toISOString()},{source:'recipes',cached:0,fresh:0,status:'missing',oldest_at:null,newest_at:null},{source:'invention',cached:2,fresh:0,status:'stale',oldest_at:new Date(Date.now()-90000000).toISOString(),newest_at:new Date(Date.now()-90000000).toISOString()}]}));
  };
  try{
    const updating={source:'market',cached:19000,fresh:0,status:'stale',completed_pages:240,total_pages:600};
    if(a.percentage(updating)!=='40%'||!a.text(updating).includes('updating')||!a.detail(updating).includes('240 of 600'))throw Error('Market page download progress');
    await a.refresh();await a.$nextTick();
    if(a.formatAge(new Date(a.now-(3*1440+20*60+13)*60000).toISOString())!=='3d 20h 13m')throw Error('Day/hour/minute formatting');
    if(a.error||header.querySelectorAll('.freshness-source').length!==4)throw Error('Freshness sources missing');
    if(!a.text(a.sources[1]).includes('partial')||!a.text(a.sources[3]).includes('due')||!a.text(a.sources[2]).includes('no data'))throw Error('Freshness status misleading');
    if(a.percentage(a.sources[0])!=='100%'||a.percentage(a.sources[1])!=='50%'||a.percentage(a.sources[2])!=='--'||a.percentage(a.sources[3])!=='0%')throw Error('Freshness percentages incorrect');
    if(a.percentage({cached:10000,fresh:9999})==='100%')throw Error('Partial cache rounded to fully fresh');
    if(header.querySelectorAll('.freshness-percent').length!==4)throw Error('Freshness percentages missing from header');
    if(!a.detail(a.sources[1]).includes('1 of 2'))throw Error('Partial cache counts missing');
    a.hub='amarr';a.changeHub();await a.refresh();await a.$nextTick();
    if(localStorage.getItem('eve.freshness.hub')!=='amarr')throw Error('Freshness hub not persisted');
    failed=true;await a.refresh();if(!a.error)throw Error('Freshness failure hidden');
    failed=false;await a.refresh();if(a.error)throw Error('Freshness retry failed');
    const r=header.getBoundingClientRect();if(r.top<0||r.right>innerWidth+1)throw Error('Freshness header overflow');
    return 'PASS: shared freshness ages, partial cache, hub persistence, failures and retry';
  }finally{window.fetch=original;if(stored===null)localStorage.removeItem('eve.freshness.hub');else localStorage.setItem('eve.freshness.hub',stored);}
}
