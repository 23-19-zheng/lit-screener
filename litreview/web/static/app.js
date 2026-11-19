const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {dataset:null, preview:[], criteria:[], reviewers:[], arbiter:null, tasks:[], currentTask:null, timer:null};
const labels = {pending:'等待启动',running:'运行中',cancelling:'正在取消',cancelled:'已取消',completed:'已完成',failed:'失败',interrupted:'待恢复',reviewing:'评审中',arbitrating:'仲裁中'};
async function api(url, options={}) {
  if (options.body && !(options.body instanceof FormData)) {options.headers={'Content-Type':'application/json'}; options.body=JSON.stringify(options.body);}
  const res = await fetch(url, options); let data;
  try {data=await res.json();} catch {data={detail:`请求失败 (${res.status})`};}
  if (!res.ok) throw new Error(data.detail || '请求失败'); return data;
}
/* 浮动提示：用 popover 进入顶层，弹窗打开时也可见；每次重新 show 以盖在最新弹窗之上 */
function notify(message, error=false) {
  const el = $('#notice');
  clearTimeout(notify.timer);
  if (el.matches(':popover-open')) el.hidePopover();
  if (!message) return;
  el.textContent = message;
  el.className = `notice${error ? ' error' : ''}`;
  el.showPopover();
  notify.timer = setTimeout(() => el.hidePopover(), error ? 10000 : 5000);
}
/* 页内确认/输入框，替代原生 confirm/prompt。input 为 null 时返回 true/false，否则返回输入文本或 null */
function ask({title, message='', okText='确认', danger=false, input=null}) {
  const dialog = $('#ask-dialog'), field = $('#ask-input'), ok = $('#ask-ok');
  $('#ask-title').textContent = title;
  $('#ask-message').textContent = message;
  field.classList.toggle('hidden', input === null);
  field.required = input !== null;
  field.value = input ?? '';
  ok.textContent = okText;
  ok.classList.toggle('danger', danger);
  dialog.returnValue = '';
  dialog.showModal();
  if (input !== null) field.select();
  return new Promise(resolve => dialog.addEventListener('close', () => {
    const accepted = dialog.returnValue === 'ok';
    resolve(input === null ? accepted : accepted ? field.value.trim() : null);
  }, {once: true}));
}
function switchView(name) {$$('.view').forEach(v=>v.classList.toggle('hidden',v.id!==`view-${name}`)); $$('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name)); $('#page-title').textContent={workspace:'筛选工作台',tasks:'任务与结果',compare:'配置对比'}[name]; if(name==='tasks') loadTasks(); if(name==='compare') renderCompareSelect();}
function goStep(n) {const launch=n===3;const panel=launch?2:n;$$('.step-panel').forEach(p=>p.classList.toggle('hidden',p.id!==`step-${panel}`));$('#criteria-step').classList.toggle('hidden',launch);$('#launch-step').classList.toggle('hidden',!launch);$$('.step').forEach(s=>s.classList.toggle('active',+s.dataset.step<=n));window.scrollTo({top:0,behavior:'smooth'});if(launch)renderLaunch();}
function modelCard(spec, index, arbiter=false) {return `<div class="reviewer" data-index="${index??''}"><div class="reviewer-title"><span>${arbiter?'ARB':'R'+(index+1)} · ${arbiter?'分歧仲裁':'独立评审'}</span>${!arbiter&&state.reviewers.length>1?`<button class="delete remove-reviewer" data-index="${index}" title="删除">×</button>`:''}</div><label>模型名称<input class="model" value="${esc(spec.model)}" placeholder="模型 ID"></label><div class="form-row real-model"><label>API 端点<input class="base-url" value="${esc(spec.base_url||'')}"></label><label>密钥环境变量<input class="api-key-env" value="${esc(spec.api_key_env||'ARK_API_KEY')}"></label></div><div class="form-row"><label class="real-model">温度<input class="temperature" type="number" min="0" max="2" step=".1" value="${spec.temperature??0}"></label><label class="real-model">密钥状态<span class="key-state" style="display:block;padding:7px 0">启动时校验环境变量</span></label></div></div>`;}
function renderModels() {
  $('#reviewer-list').innerHTML=state.reviewers.map((r,i)=>modelCard(r,i)).join('');
  $('#reviewer-count').textContent=`${state.reviewers.length} 位评审`;
  $('#arbiter-card').innerHTML=modelCard(state.arbiter,null,true);
  $('#arbiter-settings').classList.toggle('hidden',state.reviewers.length<2);
  $('#use-mock').checked=state.reviewers.every(r=>r.provider==='mock');
  $$('.real-model').forEach(e=>e.classList.toggle('hidden',$('#use-mock').checked));
  $$('.remove-reviewer').forEach(b=>b.onclick=()=>{readModels();state.reviewers.splice(+b.dataset.index,1);renderModels();});
}
function readModels() {const cards=$$('#reviewer-list .reviewer'); cards.forEach((c,i)=>{const r=state.reviewers[i]; r.model=$('.model',c).value.trim();r.base_url=$('.base-url',c).value.trim();r.api_key_env=$('.api-key-env',c).value.trim();r.temperature=+$('.temperature',c).value||0;});const c=$('#arbiter-card .reviewer'); if(c){state.arbiter.model=$('.model',c).value.trim();state.arbiter.base_url=$('.base-url',c).value.trim();state.arbiter.api_key_env=$('.api-key-env',c).value.trim();state.arbiter.temperature=+$('.temperature',c).value||0;}}
function criterionCard(c,i) {return `<div class="criterion" data-index="${i}"><div class="criterion-head"><input class="criterion-id" value="${esc(c.id)}" aria-label="判据ID"><input class="criterion-name" value="${esc(c.name)}" placeholder="判据名称"><button class="delete remove-criterion" data-index="${i}" title="删除">×</button></div><label>判定问题<textarea class="criterion-question" rows="2">${esc(c.question)}</textarea></label><label>判定指引（纳入 / 排除 / 边界）<textarea class="criterion-guidance" rows="5">${esc(c.guidance||'')}</textarea></label></div>`;}
function renderCriteria() {$('#criteria-list').innerHTML=state.criteria.map(criterionCard).join('');$$('.remove-criterion').forEach(b=>b.onclick=()=>{readCriteria();if(state.criteria.length===1)return notify('至少保留一个筛选判据',true);state.criteria.splice(+b.dataset.index,1);renderCriteria();});}
function readCriteria() {$$('#criteria-list .criterion').forEach((el,i)=>{state.criteria[i]={id:$('.criterion-id',el).value.trim(),name:$('.criterion-name',el).value.trim(),question:$('.criterion-question',el).value.trim(),guidance:$('.criterion-guidance',el).value.trim()};});}
async function upload(files) {
  if(!files.length)return; const list=$('#upload-list');list.innerHTML=[...files].map(f=>`<div class="file-item">${esc(f.name)}<span>${(f.size/1024/1024).toFixed(2)} MB</span></div>`).join('');
  const form=new FormData();[...files].forEach(f=>form.append('files',f));
  try {notify(`正在解析 ${files.length} 个文件，请稍候…`);const data=await api('/api/datasets',{method:'POST',body:form});state.dataset=data.dataset;state.preview=data.preview;renderDataset();notify(`数据集解析完成：${data.dataset.stats.unique.toLocaleString()} 篇去重文献。`);} catch(e){state.dataset=null;$('#dataset-summary').classList.add('hidden');notify(e.message,true);}
}
function renderDataset() {const d=state.dataset,s=d.stats;$('#dataset-summary').classList.remove('hidden');$('#dataset-metrics').innerHTML=[['原始题录',s.raw,'上传文件中的记录'],['去重后文献',s.unique,'实际数据集规模'],['缺少摘要',s.missing_abstract,'可按配置剔除'],['缺少 DOI',s.missing_doi,'以其他 ID / 标题匹配']].map(([k,v,n])=>`<div class="metric"><small>${k}</small><b>${Number(v).toLocaleString()}</b><span>${n}</span></div>`).join('');$('#dataset-name').textContent=d.name;$('#preview-body').innerHTML=state.preview.map(r=>`<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.year)}</td><td class="truncate">${esc(r.title)}</td><td>${r.abstract?`${r.abstract.length.toLocaleString()} 字符`:'<span class="no">缺失</span>'}</td><td>${esc(r.doctype)}</td></tr>`).join('');$('#format-note').textContent=d.files.some(f=>f.endsWith('.ris'))?'提示：RIS 的 JOUR 不能区分 Article 与 Review。如需按文献类型精确过滤，建议使用对应 WoS TXT。':'已按完整文献保留标题和摘要，多篇分块时不会截断摘要。';}
function configPayload() {readCriteria();readModels();const filters={};if($('#filter-language').value.trim())filters.language=$('#filter-language').value.trim();if($('#date-from').value.trim())filters.date_from=$('#date-from').value.trim();if($('#date-to').value.trim())filters.date_to=$('#date-to').value.trim();return {criteria:{domain:$('#domain').value.trim(),pack:'web_custom',logic:$('#logic').value,criteria:state.criteria},reviewers:state.reviewers,arbiter:state.reviewers.length>1?state.arbiter:null,filters,require_abstract:$('#require-abstract').checked,knowledge_top_k:+$('#top-k').value||4,chunk_size:+$('#chunk-size').value||20,workers:+$('#workers').value||8,char_budget:+$('#char-budget').value||60000,limit:+$('#limit').value||0};}
function renderLaunch() {const cfg=configPayload(),count=state.dataset.stats.unique;const estimated=Math.min(count,cfg.limit||count);notify('');$('#launch-summary').innerHTML=[['数据集',state.dataset.name],['预计评审文献',`${estimated.toLocaleString()} 篇`],['评审团队',`${cfg.reviewers.length} 位评审 + ${cfg.arbiter?'1 位仲裁':'无仲裁'}`],['筛选判据',`${cfg.criteria.criteria.length} 条 · ${cfg.criteria.logic}`],['分块策略',`每块至多 ${cfg.chunk_size} 篇 · 评审约 ${Math.ceil(estimated/cfg.chunk_size)*cfg.reviewers.length} 次请求`],['模型类型',cfg.reviewers.every(r=>r.provider==='mock')?'Mock · 免费流程验证':'真实模型 · 产生 API 费用']].map(([k,v])=>`<div class="summary-item"><small>${k}</small><b>${esc(v)}</b></div>`).join('');}
async function loadTasks() {try{state.tasks=await api('/api/tasks');renderTasks();}catch(e){notify(e.message,true);}}
function taskSummary(t) {
  if (t.status === 'failed') return esc(t.error);
  if (t.status === 'completed') return `纳入 ${t.metrics.include||0} · 排除 ${t.metrics.exclude||0} · 无法判定 ${t.metrics.undetermined||0}`;
  return `${labels[t.phase]||t.phase} · ${t.progress}/${t.total||'—'} 分块`;
}
function taskActions(t) {
  const running = ['running','pending','cancelling'].includes(t.status);
  // 失败/取消/中断，或已完成但有失败分块：重试只补跑未成功的分块，已完成的分块直接复用
  const retryable = ['failed','cancelled','interrupted'].includes(t.status) || (t.status === 'completed' && t.metrics.failed_requests > 0);
  return [
    `<button class="secondary open-task" data-id="${t.id}">查看详情</button>`,
    running ? `<button class="secondary cancel-task" data-id="${t.id}">取消</button>` : '',
    retryable ? `<button class="secondary retry-task" data-id="${t.id}">重试失败部分</button>` : '',
    `<button class="secondary clone-task" data-id="${t.id}">克隆配置</button>`,
    running ? '' : `<button class="secondary danger delete-task" data-id="${t.id}">删除</button>`,
  ].join('');
}
const statusGroups = {active:['pending','running','cancelling'], completed:['completed'], failed:['failed'], stopped:['cancelled','interrupted']};
function visibleTasks() {
  const q = $('#task-search').value.trim().toLowerCase(), group = statusGroups[$('#task-filter').value];
  return state.tasks.filter(t => (!group || group.includes(t.status)) && (!q || `${t.name} ${t.id}`.toLowerCase().includes(q)));
}
function renderTasks() {
  $('#task-count').textContent = state.tasks.length ? ` ${state.tasks.length}` : '';
  const tasks = visibleTasks();
  if (state.tasks.length && !tasks.length) {
    $('#task-list').innerHTML = '<div class="empty"><b>没有符合条件的任务</b>调整搜索词或状态筛选。</div>';
    return;
  }
  $('#task-list').innerHTML = tasks.length ? tasks.map(t => {
    const p = t.status === 'completed' ? 100 : t.total ? Math.round(t.progress / t.total * 100) : 0;
    return `<article class="task-card">
      <div class="task-top"><div><h3>${esc(t.name)}</h3><span class="task-id">${t.id}</span></div><span class="status ${t.status}">${labels[t.status]||t.status}${t.phase==='arbitrating'?' · 仲裁':''}</span></div>
      <div class="task-meta"><span>${t.config.reviewers.length} 位评审</span><span>${t.config.criteria.criteria.length} 条判据</span><span>${new Date(t.created_at).toLocaleString()}</span></div>
      <div class="progress"><i style="width:${p}%"></i></div>
      <div class="task-bottom"><span>${taskSummary(t)}</span><div class="actions">${taskActions(t)}</div></div>
    </article>`;
  }).join('') : '<div class="empty"><b>还没有筛选任务</b>在工作台上传数据集并创建第一个任务。</div>';
  $$('.open-task').forEach(b => b.onclick = () => openTask(b.dataset.id));
  $$('.cancel-task').forEach(b => b.onclick = () => taskAction(b.dataset.id, 'cancel', 'POST'));
  $$('.retry-task').forEach(b => b.onclick = () => taskAction(b.dataset.id, 'retry', 'POST', '已重新排队，只补跑未成功的分块。'));
  $$('.delete-task').forEach(b => b.onclick = async () => {
    const t = state.tasks.find(x => x.id === b.dataset.id);
    if (await ask({title: `删除任务「${t.name}」？`, message: '结果、分块记录和补跑历史将一并删除，无法恢复。', okText: '删除', danger: true}))
      taskAction(t.id, '', 'DELETE', '任务已删除。');
  });
  $$('.clone-task').forEach(b => b.onclick = () => cloneTask(b.dataset.id));
}
async function taskAction(tid, action, method, message) {
  try {
    await api(`/api/tasks/${tid}${action ? '/' + action : ''}`, {method});
    if (message) notify(message);
  } catch (e) { notify(e.message, true); }
  loadTasks();
}
async function cloneTask(tid) {try{const data=await api(`/api/tasks/${tid}/clone`,{method:'POST'});await restoreConfig(data);notify('已克隆任务配置，可只修改评审员或模型后重新运行。');}catch(e){notify(e.message,true);}}
function renderCompareSelect() {const done=state.tasks.filter(t=>t.status==='completed');$('#compare-select').innerHTML=done.length?done.map(t=>`<label class="check"><input type="checkbox" class="compare-task" value="${t.id}"><span>${esc(t.name)} <small>${t.id} · ${t.config.reviewers.length} 位评审</small></span></label>`).join(''):'<div class="empty">至少完成两个任务后才能对比。可从任务详情克隆配置。</div>';$$('.compare-task').forEach(c=>c.onchange=()=>{$('#run-compare').disabled=$$('.compare-task:checked').length<2;});}
async function runCompare() {const ids=$$('.compare-task:checked').map(c=>c.value);try{const data=await api(`/api/compare?ids=${ids.join(',')}`);$('#compare-result').innerHTML=`<div class="panel"><h3>配置与运行指标</h3><div class="table-wrap"><table><thead><tr><th>任务</th><th>评审</th><th>纳入 / 排除</th><th>仲裁率</th><th>请求</th><th>Token 合计</th><th>最终判定一致率</th></tr></thead><tbody>${data.map(t=>`<tr><td>${esc(t.name)}<br><small>${t.id}</small></td><td>${t.reviewers}<br><small>${esc(t.models.join(' / '))}</small></td><td>${t.metrics.include||0} / ${t.metrics.exclude||0}</td><td>${t.metrics.total?((t.metrics.arbitrated||0)/t.metrics.total*100).toFixed(1):0}%</td><td>${t.metrics.requests||0}</td><td>${((t.metrics.input_tokens||0)+(t.metrics.output_tokens||0)).toLocaleString()}</td><td>${t.pair_agreement!==undefined?(t.pair_agreement*100).toFixed(1)+'%':'—'}</td></tr>`).join('')}</tbody></table></div></div>`;}catch(e){notify(e.message,true);}}
$$('.nav').forEach(b=>b.onclick=()=>switchView(b.dataset.view));$$('[data-goto]').forEach(b=>b.onclick=()=>goStep(+b.dataset.goto));$('#file-input').onchange=e=>upload(e.target.files);const drop=$('#dropzone');['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag');}));['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag');}));drop.addEventListener('drop',e=>upload(e.dataTransfer.files));
$('#to-config').onclick=()=>{if(!state.dataset)return notify('请先上传并解析数据集',true);goStep(2);};$('#to-run').onclick=()=>{if(!state.dataset)return notify('数据集无效，请返回重新上传',true);readCriteria();if(state.criteria.some(c=>!c.id||!c.question))return notify('请完整填写每条判据的 ID 与问题',true);goStep(3);};$('#add-criterion').onclick=()=>{readCriteria();state.criteria.push({id:`C${state.criteria.length+1}`,name:'新判据',question:'',guidance:'纳入：\n排除：\n边界：'});renderCriteria();};$('#add-reviewer').onclick=()=>{readModels();if(state.reviewers.length>=8)return notify('最多支持 8 位评审员',true);const base={...state.reviewers[0]};delete base.name;state.reviewers.push({...base,name:`reviewer_${state.reviewers.length+1}`});renderModels();};$('#use-mock').onchange=e=>{readModels();const mock=e.target.checked;[...state.reviewers,state.arbiter].forEach(r=>{r.provider=mock?'mock':'openai_compatible';if(mock){r.model='mock-model';r.base_url='';}else if(r.model==='mock-model'){Object.assign(r,{...state.defaultModel,provider:'openai_compatible'});}});renderModels();};
$('#criteria-file').onchange=async e=>{if(!e.target.files[0])return;const body=new FormData();body.append('file',e.target.files[0]);try{readCriteria();const data=await api('/api/presets/import',{method:'POST',body});state.criteria=data.criteria;$('#domain').value=data.domain||'';renderCriteria();notify('判据 YAML 已导入，请检查并保存为方案。');}catch(err){notify(err.message,true);}};$('#save-preset').onclick=async()=>{closeMenus();const name=await ask({title:'保存为筛选方案',message:'方案保存判据、研究领域与组合逻辑，可在「载入判据」中复用。',okText:'保存',input:$('#domain').value||'我的筛选方案'});if(!name)return;readCriteria();try{await api('/api/presets',{method:'POST',body:{name,content:{domain:$('#domain').value,criteria:state.criteria,logic:$('#logic').value}}});notify('筛选方案已保存到本机。');await loadPresets();}catch(e){notify(e.message,true);}};$('#knowledge-file').onchange=e=>{const f=e.target.files[0];if(!f)return;const reader=new FileReader();reader.onload=()=>{$('#knowledge').value=reader.result;notify(`已载入知识文件 ${f.name}`);};reader.readAsText(f);};
$('#start-task').onclick=async()=>{const btn=$('#start-task');btn.disabled=true;try{const payload={name:$('#task-name').value.trim(),dataset_id:state.dataset.id,knowledge:$('#knowledge').value,config:configPayload()};if(!payload.config.reviewers.every(r=>r.provider==='mock')&&!await ask({title:'调用真实模型？',message:'即将调用真实模型并可能产生 API 费用。',okText:'确认启动'}))return;const task=await api('/api/tasks',{method:'POST',body:payload});notify('任务已启动，可在详情中查看进度。');switchView('tasks');openTask(task.id);}catch(e){notify(e.message,true);}finally{btn.disabled=false;}};
$('#refresh-tasks').onclick=loadTasks;$('#resume-draft').onclick=resumeDraft;$('#save-draft').onclick=async()=>{closeMenus();if(!state.dataset)return notify('请先选择数据集',true);try{await api('/api/draft',{method:'POST',body:{name:$('#task-name').value.trim(),dataset_id:state.dataset.id,knowledge:$('#knowledge').value,config:configPayload()}});$('#resume-draft').classList.remove('hidden');notify('待运行配置已保存；刷新页面后可点击右上角“继续上次配置”恢复。');}catch(e){notify(e.message,true);}};$('#back-config').onclick=()=>goStep(2);$$('.step').forEach(s=>s.onclick=()=>{if(s.dataset.step==='2'&&state.dataset)goStep(2);if(s.dataset.step==='1')goStep(1);});$('#run-compare').onclick=runCompare;$('#help-btn').onclick=()=>$('#help-dialog').showModal();$$('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());$$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d)d.close();}));
async function loadPresets() {
  state.presets = await api('/api/presets');
  renderCriteriaSource();
  renderPresetManager();
}
async function loadThemes() {
  state.themes = await api('/api/themes');
  renderCriteriaSource();
}
function renderCriteriaSource() {
  const themes = state.themes || [], presets = state.presets || [];
  $('#criteria-source').innerHTML = '<option value="">载入判据…</option>'
    + (themes.length ? `<optgroup label="主题包（判据 + 知识库 + 过滤条件）">${themes.map(t => t.error
        ? `<option disabled>${esc(t.id)}（无效：${esc(t.error)}）</option>`
        : `<option value="theme:${esc(t.id)}">${esc(t.id)} · ${esc(t.criteria.domain)}</option>`).join('')}</optgroup>` : '')
    + (presets.length ? `<optgroup label="已存方案">${presets.map(p => `<option value="preset:${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>` : '')
    + '<option value="yaml">从 YAML 文件导入…</option>';
}
function applyTheme(t) {
  state.criteria = t.criteria.criteria;
  $('#domain').value = t.criteria.domain;
  $('#logic').value = t.criteria.logic;
  $('#knowledge').value = t.knowledge;
  $('#top-k').value = t.knowledge_top_k;
  $('#require-abstract').checked = t.require_abstract;
  $('#filter-language').value = t.filters.language || '';
  $('#date-from').value = t.filters.date_from || '';
  $('#date-to').value = t.filters.date_to || '';
  renderCriteria();
  notify(`已载入主题包「${t.id}」：${t.criteria.criteria.length} 条判据、知识库与元数据过滤条件。`);
}
function applyPreset(p) {
  state.criteria = p.content.criteria;
  $('#domain').value = p.content.domain || '';
  $('#logic').value = p.content.logic || 'all';
  renderCriteria();
  notify(`已载入筛选方案「${p.name}」`);
}
$('#criteria-source').onchange = e => {
  const [kind, id] = e.target.value.split(/:(.*)/);
  e.target.value = '';
  if (kind === 'yaml') return $('#criteria-file').click();
  if (kind === 'theme') applyTheme(state.themes.find(t => t.id === id));
  if (kind === 'preset') applyPreset(state.presets.find(p => p.id === id));
};
function renderPresetManager() {
  const presets = state.presets || [];
  $('#presets-list').innerHTML = presets.length ? presets.map(p => `<div class="preset-row"><div><b>${esc(p.name)}</b><small>${esc(p.content.domain || '未填写领域')} · ${(p.content.criteria || []).length} 条判据 · ${new Date(p.updated_at).toLocaleString()}</small></div><button class="secondary danger delete-preset" data-id="${p.id}">删除</button></div>`).join('')
    : '<p class="help">还没有保存过筛选方案。</p>';
  $$('.delete-preset').forEach(b => b.onclick = async () => {
    const p = presets.find(x => x.id === b.dataset.id);
    if (!await ask({title: `删除方案「${p.name}」？`, message: '当前表单中的判据不受影响。', okText: '删除', danger: true})) return;
    try { await api(`/api/presets/${p.id}`, {method: 'DELETE'}); notify('方案已删除。'); await loadPresets(); }
    catch (e) { notify(e.message, true); }
  });
}
$('#manage-presets').onclick = () => { closeMenus(); $('#presets-dialog').showModal(); };
function closeMenus() { $$('details.menu[open]').forEach(m => m.open = false); }
document.addEventListener('click', e => { if (!e.target.closest('details.menu')) closeMenus(); });
$('#task-search').oninput = renderTasks;
$('#task-filter').onchange = renderTasks;
$('#notice').onclick = () => $('#notice').hidePopover();
async function loadDatasets() {
  const list = await api('/api/datasets');
  const select = $('#dataset-list');
  select.innerHTML = '<option value="">选择已上传的数据集</option>' + list.map(d => `<option value="${d.id}">${esc(d.name)} · ${d.stats.unique} 篇</option>`).join('');
  $('#delete-dataset').classList.add('hidden');
  select.onchange = async () => {
    $('#delete-dataset').classList.toggle('hidden', !select.value);
    if (!select.value) return;
    const data = await api(`/api/datasets/${select.value}`);
    state.dataset = data; state.preview = data.preview; delete state.dataset.preview;
    $('#upload-list').innerHTML = data.files.map(f => `<div class="file-item">${esc(f)}<span>已上传</span></div>`).join('');
    renderDataset();
    notify(`已选择数据集，共 ${data.stats.unique.toLocaleString()} 篇去重文献。`);
  };
  $('#delete-dataset').onclick = async () => {
    const d = list.find(x => x.id === select.value);
    if (!d || !await ask({title: `删除数据集「${d.name}」？`, message: `共 ${d.stats.unique} 篇，删除后无法恢复。仍被任务使用的数据集不能删除。`, okText: '删除', danger: true})) return;
    try {
      await api(`/api/datasets/${d.id}`, {method: 'DELETE'});
      if (state.dataset?.id === d.id) { state.dataset = null; $('#dataset-summary').classList.add('hidden'); $('#upload-list').innerHTML = ''; }
      notify('数据集已删除。');
      await loadDatasets();
    } catch (e) { notify(e.message, true); }
  };
}
async function resumeDraft(){const d=await api('/api/draft');if(!d.dataset_id)return notify('没有待运行的配置',true);await restoreConfig(d);notify('已恢复待运行配置，请检查评审员和模型后启动。');}
/* 克隆与恢复草稿共用：完整还原数据集、判据、模型、过滤与运行参数，避免残留上一次的表单值 */
async function restoreConfig(d){const data=await api(`/api/datasets/${d.dataset_id}`);state.dataset=data;state.preview=data.preview;delete state.dataset.preview;state.criteria=d.config.criteria.criteria;state.reviewers=d.config.reviewers||state.reviewers;state.arbiter=d.config.arbiter||state.arbiter;$('#domain').value=d.config.criteria.domain;$('#logic').value=d.config.criteria.logic||'all';$('#knowledge').value=d.knowledge||'';const filters=d.config.filters||{};$('#filter-language').value=filters.language||'';$('#date-from').value=filters.date_from||'';$('#date-to').value=filters.date_to||'';$('#require-abstract').checked=d.config.require_abstract!==false;$('#top-k').value=d.config.knowledge_top_k||4;$('#chunk-size').value=d.config.chunk_size||20;$('#workers').value=d.config.workers||8;$('#char-budget').value=d.config.char_budget||60000;$('#limit').value=d.config.limit||0;$('#task-name').value=d.name||'';renderCriteria();renderModels();renderDataset();switchView('workspace');goStep(2);}
async function init() {
  try {
    const d = await api('/api/defaults');
    state.defaultModel = d.default_model;
    state.criteria = d.criteria.criteria;
    $('#domain').value = d.criteria.domain;
    $('#logic').value = d.criteria.logic;
    const base = {provider:'mock', model:'mock-model', role:'reviewer_1', name:'reviewer_1', api_key_env:d.default_model.api_key_env, temperature:0};
    state.reviewers = [base, {...base, role:'reviewer_2', name:'reviewer_2'}];
    state.arbiter = {...base, role:'arbiter', name:'arbiter'};
    renderCriteria(); renderModels();
    await loadTasks(); await loadPresets(); await loadThemes(); await loadDatasets();
    if ((await api('/api/draft')).dataset_id) $('#resume-draft').classList.remove('hidden');
    state.timer = setInterval(pollTick, 5000);
  } catch (e) { notify('无法连接本地服务：' + e.message, true); }
}
/* 详情弹窗打开且任务在跑时只取轻量状态；任务结束后才重新加载一次完整详情 */
async function pollTick() {
  if (!$('#view-tasks').classList.contains('hidden')) loadTasks();
  if (!(state.currentTask && $('#detail-dialog').open && $('.task-live-progress'))) return;
  try {
    const t = await api(`/api/tasks/${state.currentTask}/status`);
    if (['pending','running','cancelling'].includes(t.status)) {
      const progress = $('.task-live-progress');
      if (progress) progress.textContent = `${labels[t.phase]||t.phase} · ${t.progress}/${t.total||'—'} 分块`;
    } else openTask(state.currentTask, state.detailView?.decision||'', state.detailView?.offset||0);
  } catch (e) { /* 单次轮询失败不打断，下个周期重试 */ }
}
init();
