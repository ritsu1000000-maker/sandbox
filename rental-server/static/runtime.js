(()=>{
  const root=document.querySelector('#codeEditor');
  const panel=document.querySelector('#deployConsole');
  if(!root||!panel)return;

  const id=Number(root.dataset.contractId);
  const provider=root.dataset.provider||'';
  const buildInput=document.querySelector('#buildCommand');
  const startInput=document.querySelector('#startCommand');
  const rootInput=document.querySelector('#rootDirectory');
  const alwaysOn=document.querySelector('#alwaysOn');
  const envInput=document.querySelector('#environmentVariables');
  const saveButton=document.querySelector('#saveRuntimeSettings');
  const deployButton=document.querySelector('#deployProject');
  const state=document.querySelector('#runtimeState');
  const progressWrap=document.querySelector('#deployProgressWrap');
  const progressBar=document.querySelector('#deployProgressBar');
  const progressPercent=document.querySelector('#deployProgressPercent');
  const progressTitle=document.querySelector('#deployProgressTitle');
  const output=document.querySelector('#deployOutput');

  const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content||'';

  async function api(url,options={}){
    const method=(options.method||'GET').toUpperCase();
    const headers={'Content-Type':'application/json',...(options.headers||{})};
    if(!['GET','HEAD','OPTIONS'].includes(method))headers['X-CSRF-Token']=csrf();
    const response=await fetch(url,{...options,headers});
    const data=await response.json().catch(()=>({error:'invalid response'}));
    if(response.status===401){location.href='/login?next='+encodeURIComponent(location.pathname);throw new Error('ログインが必要です。')}
    if(!response.ok){
      const error=new Error(data.error||`HTTP ${response.status}`);
      error.data=data;
      throw error;
    }
    return data;
  }

  function envToText(env){
    return Object.entries(env||{}).map(([key,value])=>`${key}=${String(value??'')}`).join('\n');
  }

  function parseEnv(){
    const result={};
    const lines=String(envInput.value||'').split(/\r?\n/);
    for(let index=0;index<lines.length;index++){
      const raw=lines[index].trim();
      if(!raw||raw.startsWith('#'))continue;
      const split=raw.indexOf('=');
      if(split<=0)throw new Error(`環境変数 ${index+1} 行目は KEY=value 形式にしてください。`);
      const key=raw.slice(0,split).trim();
      const value=raw.slice(split+1);
      if(!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(key))throw new Error(`環境変数名が正しくありません: ${key}`);
      if(['PORT','HOST','HOME','PIP_TARGET','PYTHONPATH','npm_config_cache'].includes(key))throw new Error(`${key} はシステム側で自動設定されます。`);
      result[key]=value;
    }
    return result;
  }

  function payload(){
    return {
      build_command:buildInput.value.trim(),
      start_command:startInput.value.trim(),
      root_directory:rootInput.value.trim()||'.',
      always_on:Boolean(alwaysOn.checked),
      env:parseEnv()
    };
  }

  function fill(settings){
    buildInput.value=settings.build_command||'';
    startInput.value=settings.start_command||'';
    rootInput.value=settings.root_directory||'.';
    alwaysOn.checked=settings.always_on!==false;
    envInput.value=envToText(settings.env||{});
  }

  function setRuntimeState(text,type=''){
    state.textContent=text;
    state.className='runtime-state'+(type?` ${type}`:'');
  }

  function markStep(name,status){
    const el=panel.querySelector(`[data-deploy-step="${name}"]`);
    if(!el)return;
    el.classList.remove('active','done','failed','skipped');
    if(status)el.classList.add(status);
  }

  function progress(percent,title){
    progressWrap.hidden=false;
    const safe=Math.max(0,Math.min(100,Number(percent)||0));
    progressBar.style.width=`${safe}%`;
    progressPercent.textContent=`${safe}%`;
    progressTitle.textContent=title;
  }

  function resetProgress(){
    ['save','sync','build','start'].forEach(name=>markStep(name,''));
    progress(0,'Deploy準備中');
  }

  async function loadSettings(){
    try{
      const data=await api(`/api/contracts/${id}/settings`);
      fill(data.settings||{});
      if(!data.runtime_available){
        deployButton.disabled=true;
        deployButton.title='実Deployは隔離Docker Runnerで利用できます。';
        setRuntimeState(provider==='shared'?'Shared Hosting':'Deploy unavailable','muted');
      }
    }catch(error){
      setRuntimeState('設定取得エラー','error');
      output.textContent=`ERROR: ${error.message}`;
    }
  }

  async function loadRuntime(){
    try{
      const data=await api(`/api/contracts/${id}/runtime`);
      const runtime=data.runtime||{};
      if(runtime.status==='running')setRuntimeState(runtime.always_on?'Running · 24H':'Running','running');
      else if(runtime.status==='starting')setRuntimeState('Starting…','starting');
      else if(runtime.status==='shared')setRuntimeState('Shared Hosting','running');
      else if(runtime.status==='unavailable')setRuntimeState('Deploy unavailable','muted');
      else setRuntimeState('Stopped','stopped');
    }catch(error){
      setRuntimeState('Runtime offline','error');
    }
  }

  async function saveSettings(showOutput=true){
    const body=payload();
    saveButton.disabled=true;
    try{
      const data=await api(`/api/contracts/${id}/settings`,{method:'PUT',body:JSON.stringify(body)});
      fill(data.settings||body);
      if(showOutput)output.textContent='設定を保存しました。';
      return data.settings||body;
    }finally{
      saveButton.disabled=false;
    }
  }

  function renderDeployResult(data){
    const lines=[];
    for(const step of data.steps||[]){
      const icon=step.status==='done'?'✓':step.status==='skipped'?'−':step.status==='failed'?'×':'•';
      lines.push(`${icon} ${step.id}: ${step.message||step.status}`);
    }
    if(data.build_output){
      lines.push('', '--- Build Output ---', data.build_output.trimEnd());
    }
    lines.push('', 'Deploy completed.');
    output.textContent=lines.join('\n');
  }

  function renderDeployError(error){
    const data=error.data||{};
    const lines=[`ERROR: ${error.message}`];
    for(const step of data.steps||[]){
      lines.push(`${step.status==='done'?'✓':'×'} ${step.id}: ${step.message||step.status}`);
    }
    if(data.output)lines.push('', '--- Build Output ---', String(data.output).trimEnd());
    output.textContent=lines.join('\n');
  }

  async function deploy(){
    deployButton.disabled=true;
    saveButton.disabled=true;
    resetProgress();
    output.textContent='Deployを開始します…';
    try{
      markStep('save','active');progress(10,'設定を保存中');
      const settings=await api(`/api/contracts/${id}/settings`,{method:'PUT',body:JSON.stringify(payload())});
      fill(settings.settings||{});
      markStep('save','done');

      markStep('sync','active');progress(35,'プロジェクトを隔離Runnerへ同期中');
      await new Promise(resolve=>setTimeout(resolve,120));
      markStep('sync','done');
      markStep('build','active');progress(55,'Build Commandを実行中');

      const data=await api(`/api/contracts/${id}/deploy`,{method:'POST',body:JSON.stringify(settings.settings||payload())});
      const buildStep=(data.steps||[]).find(step=>step.id==='build');
      markStep('build',buildStep?.status==='skipped'?'skipped':'done');
      markStep('start','active');progress(88,'Start Commandを起動中');
      await new Promise(resolve=>setTimeout(resolve,180));
      markStep('start','done');progress(100,'Deploy完了');
      renderDeployResult(data);
      setRuntimeState(alwaysOn.checked?'Starting · 24H':'Starting…','starting');
      setTimeout(loadRuntime,1200);
    }catch(error){
      const steps=error.data?.steps||[];
      for(const step of steps)markStep(step.id,step.status==='done'?'done':step.status==='skipped'?'skipped':'failed');
      const failed=steps.find(step=>step.status==='failed');
      if(failed)markStep(failed.id,'failed');
      progress(Number(progressPercent.textContent.replace('%',''))||55,'Deploy失敗');
      renderDeployError(error);
      setRuntimeState('Deploy failed','error');
    }finally{
      saveButton.disabled=false;
      deployButton.disabled=provider!=='runner';
    }
  }

  saveButton.addEventListener('click',async()=>{
    try{await saveSettings(true)}catch(error){output.textContent=`ERROR: ${error.message}`}
  });
  deployButton.addEventListener('click',deploy);

  Promise.all([loadSettings(),loadRuntime()]);
})();
