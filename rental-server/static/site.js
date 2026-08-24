const STORE='rental-server-items-v1';
const PLAN_META={
  free:{name:'500MB',storage:'500MB',price:0,ram:'128MB',cpu:'0.1'},
  small:{name:'1GB',storage:'1GB',price:500,ram:'256MB',cpu:'0.25'},
  medium:{name:'10GB',storage:'10GB',price:1500,ram:'512MB',cpu:'0.5'},
  large:{name:'50GB',storage:'50GB',price:2000,ram:'1GB',cpu:'1.0'},
  xlarge:{name:'100GB',storage:'100GB',price:4000,ram:'2GB',cpu:'2.0'}
};
const TEMPLATE_META={
  'python-web':{name:'Python Web',short:'PY',desc:'Flask / Python向け'},
  'node-web':{name:'Node.js Web',short:'JS',desc:'Node.jsアプリ向け'},
  'nginx':{name:'Nginx',short:'NX',desc:'静的サイト・配信向け'}
};
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
function yen(v){return `¥${Number(v||0).toLocaleString('ja-JP')}`}
function items(){try{return JSON.parse(localStorage.getItem(STORE)||'[]')}catch{return []}}
function save(list){localStorage.setItem(STORE,JSON.stringify(list))}
function remember(name,key){const list=items().filter(x=>x.name!==name);list.push({name,key});save(list)}
function forget(name){save(items().filter(x=>x.name!==name))}
function keyFor(name){return items().find(x=>x.name===name)?.key||''}
function message(text,ok=false){const el=$('#message');if(!el)return;el.textContent=text;el.className='msg '+(ok?'ok':'err');window.clearTimeout(el._timer);el._timer=setTimeout(()=>el.className='msg',5000)}
async function api(path,options={}){const r=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const data=await r.json().catch(()=>({error:'invalid response'}));if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);return data}

function initCustomSelect(){
  document.querySelectorAll('[data-custom-select]').forEach(root=>{
    const hidden=root.querySelector('input[type="hidden"]');
    const trigger=root.querySelector('.select-trigger');
    const menu=root.querySelector('.select-menu');
    const label=root.querySelector('[data-select-label]');
    const desc=root.querySelector('[data-select-desc]');
    const icon=root.querySelector('[data-select-icon]');
    const options=[...root.querySelectorAll('.select-option')];
    const choose=value=>{
      const meta=TEMPLATE_META[value]||TEMPLATE_META['python-web'];
      hidden.value=value;label.textContent=meta.name;desc.textContent=meta.desc;icon.textContent=meta.short;
      options.forEach(o=>o.classList.toggle('selected',o.dataset.value===value));
      root.classList.remove('open');trigger.setAttribute('aria-expanded','false');
    };
    trigger.addEventListener('click',()=>{const open=!root.classList.contains('open');document.querySelectorAll('[data-custom-select].open').forEach(x=>x.classList.remove('open'));root.classList.toggle('open',open);trigger.setAttribute('aria-expanded',String(open))});
    options.forEach(o=>o.addEventListener('click',()=>choose(o.dataset.value)));
    document.addEventListener('click',e=>{if(!root.contains(e.target)){root.classList.remove('open');trigger.setAttribute('aria-expanded','false')}});
    choose(hidden.value||'python-web');
  });
}

function initCreatePage(){
  const form=$('#createForm');if(!form)return;
  const choices=[...document.querySelectorAll('[data-plan-choice]')];
  const planInput=$('#plan');
  const selectedText=$('#selectedPlanText');
  const requested=new URLSearchParams(location.search).get('plan');
  let current=PLAN_META[requested]?requested:'free';
  function selectPlan(id){current=PLAN_META[id]?id:'free';planInput.value=current;choices.forEach(b=>b.classList.toggle('active',b.dataset.planChoice===current));const p=PLAN_META[current];selectedText.textContent=`選択中：${p.name} / ${yen(p.price)} 月 · RAM ${p.ram} · CPU ${p.cpu}`}
  choices.forEach(b=>b.addEventListener('click',()=>selectPlan(b.dataset.planChoice)));
  selectPlan(current);
  form.addEventListener('submit',async e=>{
    e.preventDefault();
    const name=$('#name').value.trim().toLowerCase();
    try{
      const data=await api('/api/instances',{method:'POST',body:JSON.stringify({name,template:$('#template').value,plan:planInput.value})});
      remember(data.instance.name,data.manage_key);message('サーバーを作成しました。マイサーバーへ移動します。',true);setTimeout(()=>location.href='/servers',700);
    }catch(err){message(err.message)}
  });
}

async function loadServers(){
  const root=$('#instances');if(!root)return;
  const stored=items();
  if(!stored.length){root.innerHTML='<div class="empty">まだサーバーがありません。<br><a href="/create" style="color:#1768c4;font-weight:800">サーバーを作成する</a></div>';return}
  const cards=[];
  for(const saved of stored){
    try{
      const data=await api(`/api/instances/${encodeURIComponent(saved.name)}`,{headers:{'X-Instance-Key':saved.key}});
      const i=data.instance;
      const plan=PLAN_META[i.plan]||{storage:i.storage_gb?`${i.storage_gb}GB`:'-',price:i.price_yen||0,ram:'-',cpu:'-'};
      const storage=i.storage_gb===0.5?'500MB':(i.storage_gb?`${i.storage_gb}GB`:plan.storage);
      const directUrl=i.url||((typeof i.host_port==='number')?`${location.protocol}//${location.hostname}:${i.host_port}`:null);
      const runtime=TEMPLATE_META[i.template]?.name||i.template;
      cards.push(`<article class="server-card">
        <div class="server-head"><span class="server-name">${esc(i.name)}</span><span class="tag status-${esc(i.status)}">${esc(i.status)}</span></div>
        <span class="plan-badge">${esc(storage)} · ${esc(yen(i.price_yen??plan.price))}/月 · RAM ${esc(plan.ram)} · CPU ${esc(plan.cpu)}</span>
        <div class="meta">実行環境：${esc(runtime)}<br>Service：${esc(i.container_id)}<br>${directUrl?`URL：<a href="${esc(directUrl)}" target="_blank" rel="noopener">${esc(directUrl)}</a>`:'URL：準備中'}</div>
        <div class="actions">
          <button class="primary-action" onclick="serverAction('${esc(i.name)}','start')">Start</button>
          <button onclick="serverAction('${esc(i.name)}','stop')">Stop</button>
          <button onclick="serverAction('${esc(i.name)}','restart')">Restart</button>
          <button onclick="showLogs('${esc(i.name)}')">Logs</button>
          <button class="danger" onclick="removeServer('${esc(i.name)}')">Delete</button>
        </div>
        <div class="keybox">管理キーはこのブラウザに保存されています。</div>
        <div id="logs-${esc(i.name)}" class="logs"></div>
      </article>`);
    }catch(err){cards.push(`<article class="server-card"><div class="server-name">${esc(saved.name)}</div><div class="meta">読み込み失敗：${esc(err.message)}</div><div class="actions"><button class="danger" onclick="forgetServer('${esc(saved.name)}')">この端末から削除</button></div></article>`)}
  }
  root.innerHTML=cards.join('');
}
async function serverAction(name,action){try{await api(`/api/instances/${encodeURIComponent(name)}/${action}`,{method:'POST',headers:{'X-Instance-Key':keyFor(name)}});await loadServers()}catch(err){alert(err.message)}}
async function removeServer(name){if(!confirm(`${name} を削除しますか？`))return;try{await api(`/api/instances/${encodeURIComponent(name)}`,{method:'DELETE',headers:{'X-Instance-Key':keyFor(name)}});forget(name);await loadServers()}catch(err){alert(err.message)}}
async function showLogs(name){try{const d=await api(`/api/instances/${encodeURIComponent(name)}/logs`,{headers:{'X-Instance-Key':keyFor(name)}});const el=document.getElementById(`logs-${name}`);el.style.display='block';el.textContent=d.logs||'(no logs)'}catch(err){alert(err.message)}}
function forgetServer(name){forget(name);loadServers()}

function initImportPage(){
  const form=$('#importForm');if(!form)return;
  form.addEventListener('submit',async e=>{
    e.preventDefault();const name=$('#importName').value.trim().toLowerCase();const key=$('#importKey').value.trim();
    if(!name||!key){message('サーバー名と管理キーを入力してください');return}
    try{await api(`/api/instances/${encodeURIComponent(name)}`,{headers:{'X-Instance-Key':key}});remember(name,key);message('サーバーを追加しました。',true);setTimeout(()=>location.href='/servers',650)}catch(err){message(err.message)}
  });
}

document.addEventListener('DOMContentLoaded',()=>{initCustomSelect();initCreatePage();initImportPage();loadServers()});
