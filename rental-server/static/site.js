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
const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content||'';
function yen(v){return `¥${Number(v||0).toLocaleString('ja-JP')}`}
function message(text,ok=false){const el=$('#message');if(!el)return;el.textContent=text;el.className='msg '+(ok?'ok':'err');window.clearTimeout(el._timer);el._timer=setTimeout(()=>el.className='msg',6000)}
async function api(path,options={}){
  const method=(options.method||'GET').toUpperCase();
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(!['GET','HEAD','OPTIONS'].includes(method))headers['X-CSRF-Token']=csrf();
  const r=await fetch(path,{...options,headers});
  const data=await r.json().catch(()=>({error:'invalid response'}));
  if(r.status===401){location.href='/login?next='+encodeURIComponent(location.pathname);throw new Error('ログインが必要です。')}
  if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}
function normalizeName(raw){return String(raw||'').trim().toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'').replace(/-+/g,'-').replace(/^-|-$/g,'').slice(0,32)}
function formatDate(value){if(!value)return '-';const d=new Date(value);return Number.isNaN(d.getTime())?String(value).slice(0,10):d.toLocaleDateString('ja-JP')}

function initCustomSelect(){
  document.querySelectorAll('[data-custom-select]').forEach(root=>{
    const hidden=root.querySelector('input[type="hidden"]');
    const trigger=root.querySelector('.select-trigger');
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
  const nameInput=$('#name');
  const requested=new URLSearchParams(location.search).get('plan');
  let current=PLAN_META[requested]?requested:'free';
  function selectPlan(id){current=PLAN_META[id]?id:'free';planInput.value=current;choices.forEach(b=>b.classList.toggle('active',b.dataset.planChoice===current));const p=PLAN_META[current];selectedText.textContent=`選択中：${p.name} / ${yen(p.price)} 月 · RAM ${p.ram} · CPU ${p.cpu}${p.price?' · 支払い確認後に発行':' · 作成後すぐ発行'}`}
  choices.forEach(b=>b.addEventListener('click',()=>selectPlan(b.dataset.planChoice)));
  nameInput?.addEventListener('blur',()=>{nameInput.value=normalizeName(nameInput.value)});
  selectPlan(current);
  form.addEventListener('submit',async e=>{
    e.preventDefault();
    const name=normalizeName(nameInput.value);nameInput.value=name;
    if(!name){message('サービス名を入力してください。');return}
    const button=form.querySelector('button[type="submit"]');button.disabled=true;button.textContent='作成中…';
    try{
      const data=await api('/api/contracts',{method:'POST',body:JSON.stringify({name,template:$('#template').value,plan:planInput.value})});
      const c=data.contract;
      if(c.status==='pending_payment'){
        message('サービス設定を保存しました。支払い確認待ちです。',true);
        setTimeout(()=>location.href='/billing',650);
      }else if(c.status==='capacity_waiting'){
        message('サービスを登録しました。現在ホスティング容量の空き待ちです。',true);
        setTimeout(()=>location.href=`/servers/${c.id}`,650);
      }else{
        message('ホスティングサービスを作成しました。',true);
        setTimeout(()=>location.href=`/servers/${c.id}`,650);
      }
    }catch(err){message(err.message)}finally{button.disabled=false;button.textContent='この内容で作成'}
  });
}

async function loadContractDetail(){
  const root=$('#serverDetail');if(!root)return;
  const id=root.dataset.contractId;
  try{
    const data=await api(`/api/contracts/${encodeURIComponent(id)}`);
    const c=data.contract;const i=data.instance||{};const meta=PLAN_META[c.plan]||{};const runtime=TEMPLATE_META[c.template]?.name||c.template;
    const directUrl=i.url||c.public_url||null;
    const serverStatus=i.status||(c.status==='active'?'準備中':c.status);
    if(c.status==='pending_payment'){
      root.innerHTML=`<div class="detail-panel"><span class="detail-kicker">PAYMENT REQUIRED</span><h2>${esc(c.name)}</h2><p class="detail-help">このサービスは支払い確認待ちです。決済が確認されるまでホスティング環境は発行されません。</p><a class="button button-primary" href="/billing">プラン・請求を確認</a></div>`;return;
    }
    if(c.status==='capacity_waiting'){
      root.innerHTML=`<div class="detail-panel"><span class="detail-kicker">CAPACITY WAITING</span><h2>${esc(c.name)}</h2><p class="detail-help">サービス設定は保存されていますが、現在のRender WorkspaceがHobby Tierのサービス上限に達しているため、ホスティング環境は空き待ちです。</p><a class="button button-outline" href="/dashboard">ダッシュボードへ</a></div>`;return;
    }
    if(c.status==='canceled'){
      root.innerHTML=`<div class="detail-panel"><span class="detail-kicker">INACTIVE</span><h2>${esc(c.name)}</h2><p class="detail-help">このサービスは利用終了済みです。</p><a class="button button-outline" href="/dashboard">ダッシュボードへ</a></div>`;return;
    }
    root.innerHTML=`
      <div class="detail-grid">
        <section class="detail-panel detail-main">
          <div class="detail-title-row"><div><span class="detail-kicker">SERVICE #${esc(c.id)}</span><h2>${esc(c.name)}</h2></div><span class="tag status-${esc(i.status||c.status)}">${esc(serverStatus)}</span></div>
          <div class="detail-stat-grid">
            <div class="detail-stat"><span>プラン</span><strong>${esc(c.plan_name||meta.name)}</strong><small>${esc(yen(c.price_yen))} / 月</small></div>
            <div class="detail-stat"><span>実行環境</span><strong>${esc(runtime)}</strong><small>${esc(c.provider||'-')}</small></div>
            <div class="detail-stat"><span>RAM</span><strong>${esc(c.memory||meta.ram)}</strong><small>プラン値</small></div>
            <div class="detail-stat"><span>CPU</span><strong>${esc(c.cpu??meta.cpu)}</strong><small>プラン値</small></div>
          </div>
          <div class="detail-meta-list">
            <div><span>サービス状態</span><strong>${esc(c.status)}</strong></div>
            <div><span>次回更新</span><strong>${esc(formatDate(c.renews_at))}</strong></div>
            <div><span>Service ID</span><code>${esc(i.container_id||'準備中')}</code></div>
            <div><span>Region</span><strong>${esc(i.region||'-')}</strong></div>
            <div><span>Public URL</span>${directUrl?`<a href="${esc(directUrl)}" target="_blank" rel="noopener">${esc(directUrl)}</a>`:'<strong>準備中</strong>'}</div>
          </div>
          ${c.status==='active'?`<div class="detail-actions"><button class="button button-primary" onclick="contractAction(${Number(c.id)},'start')">Start</button><button class="button button-outline" onclick="contractAction(${Number(c.id)},'stop')">Stop</button><button class="button button-outline" onclick="contractAction(${Number(c.id)},'restart')">Restart</button>${directUrl?`<a class="button button-outline" href="${esc(directUrl)}" target="_blank" rel="noopener">サイトを開く</a>`:''}</div>`:''}
        </section>
        <aside class="detail-panel"><span class="detail-kicker">HOSTING PLAN</span><h3>サービス管理</h3><p class="detail-help">操作権限はログイン中のアカウントで確認されます。</p><a class="wide-action" href="/billing">プラン・請求を見る</a><button class="wide-action danger-action" onclick="cancelContract(${Number(c.id)},'${esc(c.name)}')">サービス利用を終了</button></aside>
      </div>`;
  }catch(err){root.innerHTML=`<div class="empty">読み込みに失敗しました。<br>${esc(err.message)}</div>`}
}
async function contractAction(id,action){try{await api(`/api/contracts/${id}/${action}`,{method:'POST'});await loadContractDetail()}catch(err){alert(err.message)}}
async function cancelContract(id,name){if(!confirm(`${name} の利用を終了しますか？ ホスティング環境も削除されます。`))return;try{await api(`/api/contracts/${id}/cancel`,{method:'POST'});location.href='/dashboard'}catch(err){alert(err.message)}}

document.addEventListener('DOMContentLoaded',()=>{initCustomSelect();initCreatePage();loadContractDetail()});
