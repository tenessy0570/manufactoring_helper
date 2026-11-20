async function checkProfileControls(){
  const a=Alpine.$data(document.body),fetchOriginal=window.fetch,confirmOriginal=window.confirm;
  const profiles=a.profiles,id=a.profileId,form=JSON.stringify(a.form);let fail=false,deleted=false;
  window.confirm=()=>true;
  window.fetch=async(url,options={})=>{
    if(String(url).startsWith('/api/v1/profiles')){
      if(options.method==='DELETE'){if(fail)return new Response(JSON.stringify({detail:'Cannot delete the last profile'}),{status:409});deleted=true;return new Response(null,{status:204});}
      return new Response(JSON.stringify({items:[{id:'remaining',name:'Remaining',is_default:true}]}));
    }return fetchOriginal(url,options);
  };
  try{
    a.profiles=[...profiles,{id:'server-profile',name:'Server profile'}];a.profileId='server-profile';await a.$nextTick();
    const button=document.querySelector('.profile-delete');
    if(!button||button.disabled)throw Error('Selected server profile cannot be deleted');
    await a.deleteProfile();if(!deleted||a.profileId||a.profiles.some(p=>p.id==='server-profile')||JSON.stringify(a.form)!==form)throw Error('Profile delete failed or changed settings');
    fail=true;a.profileId='remaining';await a.deleteProfile();if(!a.error.includes('last profile')||a.profileId!=='remaining')throw Error('Last-profile failure lost selection');
    const wasOpen=a.filtersOpen;a.filtersOpen=false;await a.$nextTick();await new Promise(resolve=>setTimeout(resolve,50));
    const sort=document.querySelector('[aria-label="Sort candidates"]'),show=document.querySelector('[form="opportunity-filters"][type="submit"]');
    if(!sort||sort.closest('.column-toolbar')!==show.closest('.column-toolbar')||sort.getBoundingClientRect().height===0)throw Error('Sorting hidden with filters');
    a.filtersOpen=wasOpen;
    return 'PASS: profile removal, preserved settings, last-profile feedback and always-visible sorting';
  }finally{window.fetch=fetchOriginal;window.confirm=confirmOriginal;a.profiles=profiles;a.profileId=id;a.error='';a.saveSettings();}
}
