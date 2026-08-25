(()=>{
  const root=document.querySelector('#codeEditor');
  if(!root)return;
  const id=Number(root.dataset.contractId);
  const list=document.querySelector('#fileList');
  const source=document.querySelector('#sourceCode');
  const current=document.querySelector('#currentFile');
  const meta=document.querySelector('#fileMeta');
  const status=document.querySelector('#editorStatus');
  const saveButton=document.querySelector('#saveFile');
  const newButton=document.querySelector('#newFile');
  const deleteButton=document.querySelector('#deleteFile');
  const preview=document.querySelector('#sitePreview');
  const reloadPreview=document.querySelector('#reloadPreview');
  let selected='';
  let dirty=false;

  const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content||'';
  const encodePath=p=>encodeURIComponent(p);

  async function api(url,options={}){
    const method=(options.method||'GET').toUpperCase();
    const headers={'Content-Type':'application/json',...(options.headers||{})};
    if(!['GET','HEAD','OPTIONS'].includes(method))headers['X-CSRF-Token']=csrf();
    const response=await fetch(url,{...options,headers});
    const data=await response.json().catch(()=>({error:'invalid response'}));
    if(response.status===401){location.href='/login?next='+encodeURIComponent(location.pathname);throw new Error('ログインが必要です。')}
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
    return data;
  }

  function setStatus(text,type=''){
    status.textContent=text;
    status.className='editor-status'+(type?` ${type}`:'');
  }

  function markDirty(value=true){
    dirty=value;
    setStatus(value?'未保存':'保存済み',value?'':'saved');
  }

  function refreshPreview(){
    preview.src=`/s/${id}?preview=${Date.now()}`;
  }

  async function loadFiles(prefer=''){
    const data=await api(`/api/contracts/${id}/files`);
    list.innerHTML='';
    const files=data.files||[];
    if(!files.length){list.innerHTML='<div class="editor-empty">ファイルがありません。</div>';selected='';source.value='';current.textContent='ファイルを選択';return}
    files.forEach(file=>{
      const button=document.createElement('button');
      button.type='button';
      button.className='editor-file';
      button.dataset.path=file.path;
      button.textContent=file.path;
      button.title=`${file.path} (${file.size} bytes)`;
      button.addEventListener('click',()=>selectFile(file.path));
      list.appendChild(button);
    });
    const target=files.some(f=>f.path===prefer)?prefer:(files.some(f=>f.path==='index.html')?'index.html':files[0].path);
    await selectFile(target,false);
  }

  async function selectFile(path,confirmDirty=true){
    if(confirmDirty&&dirty&&!confirm('未保存の変更があります。破棄して別のファイルを開きますか？'))return;
    const data=await api(`/api/contracts/${id}/file?path=${encodePath(path)}`);
    selected=data.path;
    source.value=data.content||'';
    current.textContent=selected;
    meta.textContent=`${new Blob([source.value]).size.toLocaleString('ja-JP')} bytes`;
    document.querySelectorAll('.editor-file').forEach(el=>el.classList.toggle('active',el.dataset.path===selected));
    markDirty(false);
  }

  async function saveFile(){
    if(!selected){setStatus('ファイルを選択してください。','error');return}
    saveButton.disabled=true;
    setStatus('保存中…');
    try{
      const data=await api(`/api/contracts/${id}/file`,{method:'PUT',body:JSON.stringify({path:selected,content:source.value})});
      meta.textContent=`${Number(data.file?.size||0).toLocaleString('ja-JP')} bytes`;
      markDirty(false);
      await loadFiles(selected);
      refreshPreview();
    }catch(error){setStatus(error.message,'error')}
    finally{saveButton.disabled=false}
  }

  async function createFile(){
    const raw=prompt('新しいファイル名を入力してください。\n例: about.html / assets/app.js');
    if(!raw)return;
    const path=raw.trim().replace(/\\/g,'/');
    try{
      await api(`/api/contracts/${id}/file`,{method:'PUT',body:JSON.stringify({path,content:''})});
      await loadFiles(path);
      source.focus();
    }catch(error){setStatus(error.message,'error')}
  }

  async function deleteFile(){
    if(!selected)return;
    if(selected==='index.html'&&!confirm('index.html を削除すると公開ページが初期画面に戻ります。削除しますか？'))return;
    if(selected!=='index.html'&&!confirm(`${selected} を削除しますか？`))return;
    try{
      await api(`/api/contracts/${id}/file`,{method:'DELETE',body:JSON.stringify({path:selected})});
      selected='';dirty=false;
      await loadFiles();
      refreshPreview();
    }catch(error){setStatus(error.message,'error')}
  }

  source.addEventListener('input',()=>{
    if(!selected)return;
    dirty=true;
    meta.textContent=`${new Blob([source.value]).size.toLocaleString('ja-JP')} bytes`;
    setStatus('未保存');
  });
  source.addEventListener('keydown',event=>{
    if(event.key==='Tab'){
      event.preventDefault();
      const start=source.selectionStart,end=source.selectionEnd;
      source.setRangeText('  ',start,end,'end');
      source.dispatchEvent(new Event('input'));
    }
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){
      event.preventDefault();saveFile();
    }
  });
  saveButton.addEventListener('click',saveFile);
  newButton.addEventListener('click',createFile);
  deleteButton.addEventListener('click',deleteFile);
  reloadPreview.addEventListener('click',refreshPreview);
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});

  loadFiles().then(refreshPreview).catch(error=>setStatus(error.message,'error'));
})();
