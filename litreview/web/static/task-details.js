/* 任务详情与人工审计：只有显式操作才重新渲染，避免滚动/展开状态被定时器打断。 */
const pathLabels = {consistent:'整体一致',single_reviewer:'单评审',arbitrated:'仲裁完成',arbitration_error:'仲裁失败',review_error:'评审失败',disputed:'待仲裁'};
const yesNo = v => v===true?'Yes':v===false?'No':'—';
const decisionOf = t => t.final_overall===true?'纳入':t.final_overall===false?'排除':'无法判定';

function taskMetrics(task){
  const m={...task.metrics,...task.usage}, a=task.audit||{};
  return `<div class="metrics four">${[['纳入',m.include||0],['排除',m.exclude||0],['整体分歧',a.overall_disagreement||0],['仲裁失败',a.arbitration_failed||0]].map(([k,v])=>`<div class="metric"><small>${k}</small><b>${v}</b></div>`).join('')}</div>
  <div class="audit-summary"><span>整体一致 <b>${a.consistent||0}</b></span><span>判据有分歧 <b>${a.criterion_disagreement||0}</b></span><span>成功仲裁 <b>${a.arbitrated||0}</b></span><span>无法判定 <b>${a.undetermined||0}</b></span><span>人工复核 <b>${m.human_review||0}</b></span></div>
  <p class="help">成功请求 ${m.requests||0} 次 · 输入 ${(m.input_tokens||0).toLocaleString()} tokens · 输出 ${(m.output_tokens||0).toLocaleString()} tokens · 失败分块 ${m.failed_requests||0}。token 不等同于费用。</p>`;
}

function chunkTable(task){
  const groups=task.error_groups||[], chunks=task.chunks||[];
  const errors=groups.length?`<div class="notice error"><b>失败原因</b>${groups.map(g=>`<p>${esc(g.reviewer)} · ${g.count} 个失败分块<br>${esc(g.error)}</p>`).join('')}</div>`:'';
  const rows=chunks.map(c=>`<tr><td>${c.kind==='review'?'独立评审':'仲裁'}</td><td>${esc(c.reviewer)}</td><td class="mono">${c.chunk_index}</td><td>${c.status==='done'?'成功':c.status==='failed'?'失败':'拆分重试'}</td><td>${(c.usage.input_tokens||0)+(c.usage.output_tokens||0)}</td><td class="error-cell">${esc(c.error)}</td></tr>`).join('');
  return `${errors}<details class="run-config"><summary>查看任务配置与分块进度（${chunks.length} 条）</summary><h4>模型与筛选配置</h4><pre>${esc(JSON.stringify(task.config,null,2))}</pre><h4>分块执行记录</h4><div class="table-wrap"><table><thead><tr><th>阶段</th><th>评审员</th><th>分块编号</th><th>状态</th><th>Token</th><th>错误</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}

async function openTask(tid,decision='',offset=0){
  try{
    const [task,results]=await Promise.all([api(`/api/tasks/${tid}`),api(`/api/tasks/${tid}/results?limit=200&offset=${offset}&decision=${decision}`)]);
    state.currentTask=tid; state.detailView={decision,offset};
    $('#detail-title').textContent=task.name;
    const live=['pending','running','cancelling'].includes(task.status)?`<p class="task-live-progress help">${labels[task.phase]||task.phase} · ${task.progress}/${task.total||'—'} 分块</p>`:'';
    const failed=(task.audit?.arbitration_failed||0)>0;
    const arb=task.config.arbiter||{};
    const retryTemperature=arb.model==='Kimi-K3.1-Pro'?1:(arb.temperature??'默认');
    $('#detail-content').innerHTML=`${task.error?`<div class="notice error">${esc(task.error)}</div>`:''}${live}${taskMetrics(task)}
      <div class="result-tabs"><button id="open-audit" class="primary">人工审计中心</button><a class="secondary" target="_blank" href="/api/tasks/${tid}/audit.html">离线 HTML 报告</a><a class="text-btn" href="/api/tasks/${tid}/export/trace">原始 JSONL</a></div>
      ${failed?`<div class="recovery-card"><h3>有 ${task.audit.arbitration_failed} 篇文献仲裁失败</h3><p>两位主评审结果都保留，无需重新评审。补跑将使用 ${esc(arb.model)}，temperature=${retryTemperature}。</p><button id="retry-arbitration" class="primary">仅补跑 ${task.audit.arbitration_failed} 篇失败仲裁</button><small>会调用真实模型；需再次确认。不会重跑一致文献。</small></div>`:''}
      <div class="result-tabs"><a class="secondary" href="/api/tasks/${tid}/export/include">下载纳入文献</a><a class="secondary" href="/api/tasks/${tid}/export/results">完整结果</a><a class="secondary" href="/api/tasks/${tid}/export/review">人工复核</a></div>
      ${chunkTable(task)}
      ${(task.recoveries||[]).length?`<details><summary>补跑历史（${task.recoveries.length} 次）</summary>${task.recoveries.map(r=>`<div class="callout"><b>${r.status}</b> · ${r.affected_ids.length} 篇 · ${esc(r.config.model)} · temperature=${r.config.temperature??'默认'}<br><small>${esc(r.created_at)} · ${esc(JSON.stringify(r.details))}</small></div>`).join('')}</details>`:''}
      <div class="result-tabs"><button class="secondary filter-result ${!decision?'selected':''}" data-decision="">全部</button><button class="secondary filter-result ${decision==='include'?'selected':''}" data-decision="include">纳入</button><button class="secondary filter-result ${decision==='exclude'?'selected':''}" data-decision="exclude">排除</button><button class="secondary filter-result ${decision==='undetermined'?'selected':''}" data-decision="undetermined">无法判定</button><span class="help">显示 ${offset+1}–${offset+results.items.length}/${results.total} 条</span>${offset>0?'<button id="prev-results" class="secondary">上一页</button>':''}${offset+results.items.length<results.total?'<button id="next-results" class="secondary">下一页</button>':''}</div>
      <div class="table-wrap"><table><thead><tr><th>判定</th><th>标题</th><th>年份</th><th>路径</th></tr></thead><tbody>${results.items.map(t=>`<tr class="open-record" data-rid="${esc(t.record_id)}"><td class="decision">${decisionOf(t)}</td><td>${esc(t.record.title)}</td><td>${esc(t.record.year)}</td><td>${pathLabels[t.path]||esc(t.path)}</td></tr>`).join('')}</tbody></table></div>
      <details style="margin-top:20px"><summary>上传人工金标准，计算 P / R / F1</summary><form id="evaluate-form"><input name="labels" type="file" accept=".csv" required><button class="primary">开始评估</button></form><div id="evaluation-result"></div></details>`;
    if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
    $('#open-audit').onclick=()=>openAudit(tid);
    if($('#retry-arbitration'))$('#retry-arbitration').onclick=()=>confirmArbitrationRetry(task);
    $$('.filter-result').forEach(b=>b.onclick=()=>openTask(tid,b.dataset.decision));
    if($('#prev-results'))$('#prev-results').onclick=()=>openTask(tid,decision,Math.max(0,offset-200));
    if($('#next-results'))$('#next-results').onclick=()=>openTask(tid,decision,offset+200);
    $$('.open-record').forEach(row=>row.onclick=()=>showRecord(results.items.find(t=>t.record_id===row.dataset.rid)));
    $('#evaluate-form').onsubmit=async e=>{e.preventDefault();const body=new FormData(e.target);try{$('#evaluation-result').textContent='评估中…';const r=await api(`/api/tasks/${tid}/evaluate`,{method:'POST',body});$('#evaluation-result').innerHTML=`<p>匹配 ${r.matched}，未匹配 ${r.unmatched}，无法判定 ${r.undetermined||0}</p><table><thead><tr><th>判据</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>${Object.entries(r.metrics).map(([k,m])=>`<tr><td>${k}</td><td>${m.precision}</td><td>${m.recall}</td><td>${m.f1}</td></tr>`).join('')}</tbody></table>`;}catch(err){$('#evaluation-result').textContent=err.message;}};
  }catch(e){notify(e.message,true);}
}

async function confirmArbitrationRetry(task){
  const count=task.audit.arbitration_failed;
  const arb=task.config.arbiter;
  if(!confirm(`仅补跑 ${count} 篇仲裁失败文献？\n\n模型：${arb.model}\ntemperature：${arb.model==='Kimi-K3.1-Pro'?1:(arb.temperature??'默认')}\n不会重新调用两位主评审，真实模型调用会产生费用。`))return;
  try{await api(`/api/tasks/${task.id}/arbitration-retry`,{method:'POST'});notify('仅补仲裁任务已启动，可刷新查看进度。');openTask(task.id);}catch(e){notify(e.message,true);}
}

function showRecord(t){
  if(!t)return;
  state.detailRecord=t.record_id;
  $('#detail-content').innerHTML=`<button id="back-task" class="text-btn">← 返回结果列表</button><h3 class="trace-title">${esc(t.record.title)}</h3><p class="help">${esc(t.record_id)} · ${esc(t.record.doi||'无 DOI')} · ${esc(t.record.year)}</p><h4>摘要</h4><div class="trace-abstract">${esc(t.record.abstract||'无摘要')}</div>${t.knowledge_used?`<details><summary>本篇检索到的领域知识</summary><div class="trace-abstract">${esc(t.knowledge_used)}</div></details>`:''}<div class="review-grid">${Object.entries(t.reviews||{}).map(([name,r])=>`<div class="review-box"><h4>${esc(name)} · ${r?.overall===true?'纳入':r?.overall===false?'排除':'无法判定'}</h4>${Object.entries(r?.answers||{}).map(([c,a])=>`<div class="criterion-answer"><b class="${a?'yes':'no'}">${esc(c)} ${yesNo(a)}</b><br>${esc(r.reasonings?.[c]||'')}</div>`).join('')}${r?.error?`<p class="no">${esc(r.error)}</p>`:''}</div>`).join('')}</div>${t.arbitration?`<div class="review-box"><h4>仲裁结果 · ${decisionOf(t)}</h4>${Object.entries(t.arbitration.answers||{}).map(([c,a])=>`<p><b class="${a?'yes':'no'}">${esc(c)} ${yesNo(a)}</b> ${esc(t.arbitration.reasonings?.[c]||'')}</p>`).join('')}</div>`:''}<div class="callout">最终路径：${pathLabels[t.path]||esc(t.path)}${t.review_reason?` · ${esc(t.review_reason)}`:''}</div>`;
  $('#back-task').onclick=()=>openTask(state.currentTask,state.detailView?.decision||'',state.detailView?.offset||0);
}

async function openAudit(tid,category='',offset=0,query=''){
  try{
    const [task,data]=await Promise.all([api(`/api/tasks/${tid}`),api(`/api/tasks/${tid}/audit?category=${category}&offset=${offset}&limit=100&q=${encodeURIComponent(query)}`)]);
    state.auditView={category,offset,query};
    $('#audit-title').textContent=`${task.name} · 人工审计`;
    const s=data.summary;
    $('#audit-content').innerHTML=`<div class="audit-summary"><span>整体一致 <b>${s.consistent}</b></span><span>整体分歧 <b>${s.overall_disagreement}</b></span><span>判据分歧 <b>${s.criterion_disagreement}</b></span><span>成功仲裁 <b>${s.arbitrated}</b></span><span>仲裁失败 <b>${s.arbitration_failed}</b></span></div>
    <div class="result-tabs"><button class="secondary audit-filter ${!category?'selected':''}" data-category="">全部文献</button><button class="secondary audit-filter ${category==='overall'?'selected':''}" data-category="overall">整体分歧</button><button class="secondary audit-filter ${category==='criteria'?'selected':''}" data-category="criteria">判据分歧</button><button class="secondary audit-filter ${category==='arbitration_error'?'selected':''}" data-category="arbitration_error">仲裁失败</button><a class="text-btn" target="_blank" href="/api/tasks/${tid}/audit.html">打印 / 离线 HTML</a></div>
    ${(task.error_groups||[]).length?`<details class="notice error"><summary><b>失败原因（${task.error_groups.reduce((n,g)=>n+g.count,0)} 个分块）</b></summary>${task.error_groups.map(g=>`<p>${esc(g.reviewer)}：${esc(g.error)}（${g.count} 块）</p>`).join('')}</details>`:''}
    <p class="help">逐篇展开查看原始摘要、各评审答案和理由；不同判据以橙色标记。显示 ${offset+1}–${offset+data.items.length}/${data.total} 条。</p><form id="audit-search" class="result-tabs"><input name="q" value="${esc(query)}" placeholder="搜索标题或 DOI"><button class="secondary">搜索</button></form>
    <div class="audit-list">${data.items.map(row=>auditRecord(row,tid)).join('')}</div>
    <div class="actions center">${offset>0?'<button id="audit-prev" class="secondary">上一页</button>':''}${offset+data.items.length<data.total?'<button id="audit-next" class="secondary">下一页</button>':''}</div>`;
    if(!$('#audit-dialog').open)$('#audit-dialog').showModal();
    $$('.audit-filter').forEach(b=>b.onclick=()=>openAudit(tid,b.dataset.category,0,query));
    $('#audit-search').onsubmit=e=>{e.preventDefault();openAudit(tid,category,0,new FormData(e.target).get('q')||'');};
    if($('#audit-prev'))$('#audit-prev').onclick=()=>openAudit(tid,category,Math.max(0,offset-100),query);
    if($('#audit-next'))$('#audit-next').onclick=()=>openAudit(tid,category,offset+100,query);
  }catch(e){notify(e.message,true);}
}

function auditRecord(row,tid){
  const t=row.trace;
  const reviews=Object.entries(t.reviews||{}).map(([name,r])=>`<section class="audit-review"><h4>${esc(name)} · ${yesNo(r?.overall)}</h4>${(t.criteria||[]).map(cid=>`<div class="criterion-answer ${row.different_criteria.includes(cid)?'criterion-diff':''}"><b>${esc(cid)} · ${yesNo(r?.answers?.[cid])}</b><p>${esc(r?.reasonings?.[cid]||'无理由')}</p></div>`).join('')}</section>`).join('');
  return `<details class="audit-record" id="audit-${esc(row.record_id)}"><summary><span class="decision">${decisionOf(t)}</span><b>${esc(row.title)}</b><span class="tag">${pathLabels[t.path]||t.path}</span>${row.different_criteria.length?`<span class="diff-label">差异：${row.different_criteria.join(', ')}</span>`:''}</summary><div class="audit-record-body"><p class="help">${esc(row.record_id)} · ${esc(row.doi||'无 DOI')}</p><details><summary>原始摘要</summary><div class="trace-abstract">${esc(t.record.abstract||'无摘要')}</div></details><details><summary>检索到的知识库内容</summary><div class="trace-abstract">${esc(t.knowledge_used||'无')}</div></details><div class="review-grid">${reviews}</div>${t.arbitration?.overall!==null&&t.arbitration?.overall!==undefined?`<section class="audit-review"><h4>仲裁 · ${decisionOf(t)}</h4>${(t.criteria||[]).map(cid=>`<p><b>${esc(cid)} · ${yesNo(t.arbitration.answers?.[cid])}</b> ${esc(t.arbitration.reasonings?.[cid]||'')}</p>`).join('')}</section>`:''}</div></details>`;
}
