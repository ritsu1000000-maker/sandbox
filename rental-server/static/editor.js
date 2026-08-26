(()=>{
  const root=document.querySelector('#codeEditor');
  if(!root)return;
  const id=Number(root.dataset.contractId);
  const provider=root.dataset.provider||'';
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
  const importZip=document.querySelector('#importZip');
  const zipInput=document.querySelector('#zipInput');
  const terminalForm=document.querySelector('#terminalForm');
  const terminalInput=document.querySelector('#terminalCommand');
  const terminalOutput=document.querySelector('#terminalOutput');
  const clearTerminal=document.querySelector('#clearTerminal');
  let selected='';
  let dirty=false;
  const commandHistory=[];
  let historyIndex=0;

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

  function refreshPreview(){preview.src=`/s/${id}?preview=${Date.now()}`}

  async function loadFiles(prefer=''){
    const data=await api(`/api/contracts/${id}/files`);
    list.innerHTML='';
    const files=data.files||[];
    if(!files.length){list.innerHTML='<div class="editor-empty">ファイルがありません。</div>';selected='';source.value='';current.textContent='ファイルを選択';return files}
    files.forEach(file=>{
      const button=document.createElement('button');
      button.type='button';button.className='editor-file';button.dataset.path=file.path;button.textContent=file.path;
      button.title=`${file.path} (${file.size} bytes)`;button.addEventListener('click',()=>selectFile(file.path));list.appendChild(button);
    });
    const target=files.some(f=>f.path===prefer)?prefer:(files.some(f=>f.path==='index.html')?'index.html':files[0].path);
    await selectFile(target,false);
    return files;
  }

  async function selectFile(path,confirmDirty=true){
    if(confirmDirty&&dirty&&!confirm('未保存の変更があります。破棄して別のファイルを開きますか？'))return;
    const data=await api(`/api/contracts/${id}/file?path=${encodePath(path)}`);
    selected=data.path;source.value=data.content||'';current.textContent=selected;
    meta.textContent=`${new Blob([source.value]).size.toLocaleString('ja-JP')} bytes`;
    document.querySelectorAll('.editor-file').forEach(el=>el.classList.toggle('active',el.dataset.path===selected));
    markDirty(false);
  }

  async function saveFile(){
    if(!selected){setStatus('ファイルを選択してください。','error');return}
    saveButton.disabled=true;setStatus('保存中…');
    try{
      const data=await api(`/api/contracts/${id}/file`,{method:'PUT',body:JSON.stringify({path:selected,content:source.value})});
      meta.textContent=`${Number(data.file?.size||0).toLocaleString('ja-JP')} bytes`;markDirty(false);await loadFiles(selected);refreshPreview();
    }catch(error){setStatus(error.message,'error')}finally{saveButton.disabled=false}
  }

  async function createFile(){
    const raw=prompt('新しいファイル名を入力してください。\n例: about.html / assets/app.js');if(!raw)return;
    const path=raw.trim().replace(/\\/g,'/');
    try{await api(`/api/contracts/${id}/file`,{method:'PUT',body:JSON.stringify({path,content:''})});await loadFiles(path);source.focus()}catch(error){setStatus(error.message,'error')}
  }

  async function deleteFile(){
    if(!selected)return;
    if(selected==='index.html'&&!confirm('index.html を削除すると公開ページが初期画面に戻ります。削除しますか？'))return;
    if(selected!=='index.html'&&!confirm(`${selected} を削除しますか？`))return;
    try{await api(`/api/contracts/${id}/file`,{method:'DELETE',body:JSON.stringify({path:selected})});selected='';dirty=false;await loadFiles();refreshPreview()}catch(error){setStatus(error.message,'error')}
  }

  const textExtensions=new Set(['html','htm','css','js','mjs','cjs','ts','tsx','jsx','json','py','txt','md','xml','yaml','yml','toml','ini','cfg','conf','env','sh','bat','cmd','ps1','java','c','cc','cpp','h','hpp','go','rs','rb','php','vue','svelte','sql','gitignore','dockerfile','properties','gradle','lock']);
  const textNames=new Set(['dockerfile','procfile','makefile','requirements.txt','package.json','package-lock.json','pnpm-lock.yaml','yarn.lock','.gitignore','.dockerignore','.env.example']);
  function isTextFile(path){const name=path.split('/').pop().toLowerCase();if(textNames.has(name))return true;const dot=name.lastIndexOf('.');return dot>=0&&textExtensions.has(name.slice(dot+1))}
  function normalizeZipPath(value){const raw=String(value||'').replace(/\\/g,'/');if(!raw||raw.startsWith('/')||raw.length>120)throw new Error(`不正なZIPパス: ${raw}`);const parts=raw.split('/');if(parts.some(p=>!p||p==='.'||p==='..')||parts.length>8)throw new Error(`不正なZIPパス: ${raw}`);return parts.join('/')}
  const u16=(view,offset)=>view.getUint16(offset,true);
  const u32=(view,offset)=>view.getUint32(offset,true);
  function findEocd(view){const start=Math.max(0,view.byteLength-65557);for(let i=view.byteLength-22;i>=start;i--){if(u32(view,i)===0x06054b50)return i}return-1}
  async function inflateRaw(bytes){if(typeof DecompressionStream==='undefined')throw new Error('このブラウザはZIP展開に対応していません。');const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));return new Uint8Array(await new Response(stream).arrayBuffer())}
  async function readZip(file){
    if(file.size>10*1024*1024)throw new Error('ZIPファイルは10MBまでです。');
    const buffer=await file.arrayBuffer();const view=new DataView(buffer);const bytes=new Uint8Array(buffer);const eocd=findEocd(view);if(eocd<0)throw new Error('ZIPの終端情報が見つかりません。');
    const count=u16(view,eocd+10);if(count>100)throw new Error('ZIP内は100ファイルまでです。');let cursor=u32(view,eocd+16);const decoder=new TextDecoder('utf-8');const entries=[];let total=0;let skipped=0;
    for(let i=0;i<count;i++){
      if(cursor+46>view.byteLength||u32(view,cursor)!==0x02014b50)throw new Error('ZIPの中央ディレクトリが壊れています。');
      const flags=u16(view,cursor+8),method=u16(view,cursor+10),compressed=u32(view,cursor+20),uncompressed=u32(view,cursor+24),nameLen=u16(view,cursor+28),extraLen=u16(view,cursor+30),commentLen=u16(view,cursor+32),external=u32(view,cursor+38),localOffset=u32(view,cursor+42);
      const name=decoder.decode(bytes.slice(cursor+46,cursor+46+nameLen));cursor+=46+nameLen+extraLen+commentLen;
      if(name.endsWith('/'))continue;if(flags&1)throw new Error('暗号化ZIPには対応していません。');if(((external>>>16)&0xF000)===0xA000)throw new Error('ZIP内のシンボリックリンクは使用できません。');
      const path=normalizeZipPath(name);if(!isTextFile(path)){skipped++;continue}if(uncompressed>512*1024)throw new Error(`${path}: 1ファイル512KBまでです。`);if(compressed>0&&uncompressed/compressed>200)throw new Error(`${path}: 圧縮率が高すぎるため展開を停止しました。`);if(method!==0&&method!==8)throw new Error(`${path}: 未対応のZIP圧縮方式です。`);
      if(localOffset+30>view.byteLength||u32(view,localOffset)!==0x04034b50)throw new Error(`${path}: ローカルヘッダーが壊れています。`);const localName=u16(view,localOffset+26),localExtra=u16(view,localOffset+28),dataStart=localOffset+30+localName+localExtra,dataEnd=dataStart+compressed;if(dataEnd>view.byteLength)throw new Error(`${path}: ZIPデータが途中で切れています。`);
      const packed=bytes.slice(dataStart,dataEnd);const unpacked=method===0?packed:await inflateRaw(packed);if(unpacked.byteLength>512*1024)throw new Error(`${path}: 展開後サイズが大きすぎます。`);if(unpacked.includes(0)){skipped++;continue}
      total+=unpacked.byteLength;if(total>5*1024*1024)throw new Error('展開するソースコードの合計は5MBまでです。');entries.push({path,content:decoder.decode(unpacked)});
    }
    if(!entries.length)throw new Error('展開できるテキスト形式のソースコードがありません。');return{entries,skipped};
  }
  async function importZipFile(file){
    setStatus('ZIPを検証中…');importZip.disabled=true;
    try{
      const {entries,skipped}=await readZip(file);const currentFiles=await api(`/api/contracts/${id}/files`);const existing=new Set((currentFiles.files||[]).map(f=>f.path));const overlaps=entries.filter(e=>existing.has(e.path));if(overlaps.length&&!confirm(`${overlaps.length}個の既存ファイルを上書きします。続行しますか？`))return;
      setStatus(`ZIP展開中 0/${entries.length}`);let done=0;for(const entry of entries){await api(`/api/contracts/${id}/file`,{method:'PUT',body:JSON.stringify(entry)});done++;setStatus(`ZIP展開中 ${done}/${entries.length}`)}
      await loadFiles(entries.some(e=>e.path==='index.html')?'index.html':entries[0].path);refreshPreview();setStatus(`ZIP展開完了: ${entries.length}ファイル${skipped?` / ${skipped}件スキップ`:''}`,'saved');
    }catch(error){setStatus(error.message,'error')}finally{importZip.disabled=false;zipInput.value=''}
  }

  function terminalWrite(text){terminalOutput.textContent+=text;terminalOutput.scrollTop=terminalOutput.scrollHeight}
  async function runTerminal(command){
    terminalWrite(`$ ${command}\n`);
    try{const data=await api(`/api/contracts/${id}/exec`,{method:'POST',body:JSON.stringify({command})});terminalWrite(data.output||'');if(data.output&&!data.output.endsWith('\n'))terminalWrite('\n');terminalWrite(`[exit ${data.exit_code}]${data.truncated?' output truncated':''}\n`)}catch(error){terminalWrite(`ERROR: ${error.message}\n`)}
  }

  source.addEventListener('input',()=>{if(!selected)return;dirty=true;meta.textContent=`${new Blob([source.value]).size.toLocaleString('ja-JP')} bytes`;setStatus('未保存')});
  source.addEventListener('keydown',event=>{
    if(event.key==='Tab'){event.preventDefault();const start=source.selectionStart,end=source.selectionEnd;source.setRangeText('  ',start,end,'end');source.dispatchEvent(new Event('input'))}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();saveFile()}
  });
  saveButton.addEventListener('click',saveFile);newButton.addEventListener('click',createFile);deleteButton.addEventListener('click',deleteFile);reloadPreview.addEventListener('click',refreshPreview);
  importZip.addEventListener('click',()=>zipInput.click());zipInput.addEventListener('change',()=>{const file=zipInput.files?.[0];if(file)importZipFile(file)});
  clearTerminal.addEventListener('click',()=>{terminalOutput.textContent=''});
  terminalForm.addEventListener('submit',async event=>{event.preventDefault();const command=terminalInput.value.trim();if(!command)return;commandHistory.push(command);historyIndex=commandHistory.length;terminalInput.value='';terminalInput.disabled=true;try{await runTerminal(command)}finally{terminalInput.disabled=false;terminalInput.focus()}});
  terminalInput.addEventListener('keydown',event=>{if(event.key==='ArrowUp'&&commandHistory.length){event.preventDefault();historyIndex=Math.max(0,historyIndex-1);terminalInput.value=commandHistory[historyIndex]||''}else if(event.key==='ArrowDown'&&commandHistory.length){event.preventDefault();historyIndex=Math.min(commandHistory.length,historyIndex+1);terminalInput.value=commandHistory[historyIndex]||''}});
  if(provider!=='runner')terminalWrite('NOTE: このサービスは共有Renderモードです。実コマンドには隔離Docker Runner接続が必要です。\n');
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});
  loadFiles().then(refreshPreview).catch(error=>setStatus(error.message,'error'));
})();
