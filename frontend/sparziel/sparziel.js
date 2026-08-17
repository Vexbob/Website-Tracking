let chartSavings=null, chartData=[], glGoalId=null, glTarget=0, glTotal=0;
let achData=[], pgData=[], logRaw=[], logFilter='all', logView='weekly';
let heatmapData=[], trophyData=[];
let loadErrors={ach:false,pg:false,log:false,hm:false,trophies:false};
const pendingDeletes = new Map();
let toastTimer=null;
let msTargetId=null;
let noteTarget=null; // {type: 'checkin'|'milestone'|'initial'|'streak_bonus', id: number}

// --- Zahl-Animation & Konfetti-State ---
let hmMetric = localStorage.getItem('vex_hm_metric') || 'all';
let prevGlTotal = null;   // vorheriger Sparbetrag (für Delta-Animation)
let prevGlPct = null;     // vorheriger Prozentwert
let prevWasComplete = false; // bereits >= 100 % erreicht?
let confettiRaf = null;   // aktuelle rAF-ID für Konfetti (Cleanup)

// --- Zahl-Count-Up-Animation ---
// Animiert eine Zahl von `from` nach `to` über `duration` ms.
// `render(v)` erhält den Zwischenwert und schreibt ihn ins DOM.
// Läuft nur bei tatsächlichem Delta; respektiert prefers-reduced-motion.
function animateNumber(from, to, duration, render){
    if(from==null || !isFinite(from) || from===to){ render(to); return; }
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(reduce || duration<=0){ render(to); return; }
    const start = performance.now();
    const delta = to - from;
    function step(now){
        const t = Math.min(1, (now - start) / duration);
        // easeOutCubic
        const e = 1 - Math.pow(1 - t, 3);
        render(from + delta * e);
        if(t < 1) requestAnimationFrame(step);
        else render(to);
    }
    requestAnimationFrame(step);
}

// --- Konfetti (Canvas, keine externe Lib) ---
function fireConfetti(opts){
    opts = opts || {};
    const canvas = document.getElementById('confettiCanvas');
    if(!canvas) return;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(reduce) return;
    const dpr = window.devicePixelRatio || 1;
    const W = window.innerWidth, H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    canvas.classList.add('show');

    const colors = ['#22c55e','#3b82f6','#f59e0b','#ec4899','#8b5cf6','#14b8a6','#eab308','#ef4444'];
    const count = opts.count || 180;
    const duration = opts.duration || 2600;
    const originX = opts.originX!=null ? opts.originX : W/2;
    const originY = opts.originY!=null ? opts.originY : H*0.35;
    const spread = opts.spread || Math.PI; // Streuwinkel (nach oben)
    const particles = [];
    for(let i=0;i<count;i++){
        const angle = -Math.PI/2 + (Math.random()-0.5)*spread;
        const speed = 6 + Math.random()*9;
        particles.push({
            x: originX,
            y: originY,
            vx: Math.cos(angle)*speed + (Math.random()-0.5)*2,
            vy: Math.sin(angle)*speed - Math.random()*2,
            g: 0.18 + Math.random()*0.12,
            drag: 0.995,
            size: 5 + Math.random()*5,
            rot: Math.random()*Math.PI*2,
            vr: (Math.random()-0.5)*0.35,
            color: colors[(Math.random()*colors.length)|0],
            shape: Math.random()<0.5 ? 'rect' : 'circle',
            life: 1
        });
    }
    const start = performance.now();
    if(confettiRaf) cancelAnimationFrame(confettiRaf);
    function frame(now){
        const elapsed = now - start;
        ctx.clearRect(0,0,W,H);
        let alive = 0;
        for(const p of particles){
            p.vx *= p.drag;
            p.vy = p.vy * p.drag + p.g;
            p.x += p.vx;
            p.y += p.vy;
            p.rot += p.vr;
            p.life = Math.max(0, 1 - elapsed/duration);
            if(p.life<=0 || p.y > H+40) continue;
            alive++;
            ctx.save();
            ctx.globalAlpha = p.life;
            ctx.translate(p.x, p.y);
            ctx.rotate(p.rot);
            ctx.fillStyle = p.color;
            if(p.shape==='rect'){
                ctx.fillRect(-p.size/2, -p.size/3, p.size, p.size*0.6);
            } else {
                ctx.beginPath();
                ctx.arc(0,0,p.size/2,0,Math.PI*2);
                ctx.fill();
            }
            ctx.restore();
        }
        if(alive>0 && elapsed<duration+400){
            confettiRaf = requestAnimationFrame(frame);
        } else {
            confettiRaf = null;
            ctx.clearRect(0,0,W,H);
            canvas.classList.remove('show');
        }
    }
    confettiRaf = requestAnimationFrame(frame);
}

function showToast(m,err){
    const t=document.getElementById('toast');
    t.innerHTML=esc(m);t.classList.toggle('err',!!err);t.classList.add('show');
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),2500);
}
function showUndoToast(message, undoFn, executeFn, delayMs=5000){
    const t=document.getElementById('toast');
    const key=Symbol();
    t.innerHTML=`<span>${esc(message)}</span><button class="undo-btn" data-undo>Rückgängig</button>`;
    t.classList.remove('err');t.classList.add('show');
    clearTimeout(toastTimer);
    const commit=()=>{
        if(pendingDeletes.has(key)){pendingDeletes.delete(key);t.classList.remove('show');executeFn();}
    };
    const undo=()=>{
        if(pendingDeletes.has(key)){clearTimeout(pendingDeletes.get(key).timer);pendingDeletes.delete(key);t.classList.remove('show');undoFn();}
    };
    const timer=setTimeout(commit, delayMs);
    pendingDeletes.set(key,{timer,executeFn:commit,undoFn:undo});
    t.querySelector('[data-undo]').addEventListener('click',undo);
}
window.addEventListener('beforeunload',()=>{
    pendingDeletes.forEach(p=>{clearTimeout(p.timer);try{p.executeFn();}catch(e){}});
});

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function pct(a,b){if(!b||b<=0)return 0;return Math.max(0,Math.min(100,(a/b)*100));}
function fmtDate(d){if(!d)return'';try{return new Date(d).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});}catch(e){return d;}}
function fmtDay(d){if(!d)return'';try{return new Date(d).toLocaleDateString('de-DE',{weekday:'long',day:'2-digit',month:'long',year:'numeric'});}catch(e){return d;}}
function fmtShortDate(d){if(!d)return'';try{return new Date(d).toLocaleDateString('de-DE',{day:'2-digit',month:'short'});}catch(e){return d;}}
function todayIso(){return new Date().toISOString().slice(0,10);}

function isoWeek(dt){
    const t=new Date(Date.UTC(dt.getFullYear(),dt.getMonth(),dt.getDate()));
    const dayNum=t.getUTCDay()||7;
    t.setUTCDate(t.getUTCDate()+4-dayNum);
    const yearStart=new Date(Date.UTC(t.getUTCFullYear(),0,1));
    return{week:Math.ceil(((t-yearStart)/86400000+1)/7),year:t.getUTCFullYear()};
}
function currentWeekInfo(){
    const now=new Date();
    const {week,year}=isoWeek(now);
    const monday=new Date(now);monday.setDate(now.getDate()-((now.getDay()||7)-1));
    const sunday=new Date(monday);sunday.setDate(monday.getDate()+6);
    return{week,year,start:monday,end:sunday};
}
function updatePeriodLabel(){
    const w=currentWeekInfo();
    const s=w.start.toLocaleDateString('de-DE',{day:'2-digit',month:'short'});
    const e=w.end.toLocaleDateString('de-DE',{day:'2-digit',month:'short',year:'numeric'});
    document.getElementById('pgPeriodLbl').textContent=`· KW ${w.week} (${s} – ${e})`;
}

function activateTab(t){
    document.querySelectorAll('.tab-btn').forEach(x=>x.classList.toggle('active',x.dataset.tab===t));
    ['dashboard','log','heatmap','trophies','ideen'].forEach(id=>{
        const el=document.getElementById('tab-'+id);
        if(el) el.style.display = id===t?'':'none';
    });
    history.replaceState(null,'','#'+t);
    if(t==='log') loadLog();
    if(t==='heatmap') loadHeatmap();
    if(t==='trophies') loadTrophies();
    if(t==='ideen'){loadSavingsGoals();loadPotentialGoals();loadFutureIdeas();}
}
function toggleForm(id){document.getElementById(id).classList.toggle('open');}
function toggleHeroEdit(){
    const e=document.getElementById('heroEdit');e.classList.toggle('open');
    if(e.classList.contains('open')){
        document.getElementById('sgName').value=document.getElementById('goalName').textContent;
        document.getElementById('sgTarget').value=glTarget;
    }
}
async function loadAll(){await Promise.all([loadSparziel(),loadAchievements(),loadProgressGoals()]);updatePeriodLabel();}

async function loadSparziel(){
    try{
        const d=await apiCall('/api/savings-goal');
        const g=d.goal||{};
        const newGoalId=g.id;
        const newTarget=Number(g.target_amount||0);
        const newTotal=Number(d.total_saved||0);
        const newPct=pct(newTotal,newTarget);
        const circ=2*Math.PI*42;

        // Bei Ziel-Wechsel (anderes Sparziel aktiviert): keine Animation, hart setzen
        const goalChanged = (glGoalId !== null && newGoalId !== glGoalId);
        const isInitialLoad = (prevGlTotal == null);
        const fromTotal = goalChanged ? newTotal : (prevGlTotal!=null ? prevGlTotal : newTotal);
        const fromPct   = goalChanged ? newPct   : (prevGlPct!=null   ? prevGlPct   : newPct);

        glGoalId=newGoalId; glTarget=newTarget; glTotal=newTotal;

        document.getElementById('goalName').textContent=g.name||'Sparziel';
        document.getElementById('stTarget').textContent=fmtEur(glTarget);

        // stTotal (€) count-up
        const elTotal = document.getElementById('stTotal');
        animateNumber(fromTotal, newTotal, 700, v => { elTotal.textContent = fmtEur(v); });

        // stMissing (€) count-up
        const elMissing = document.getElementById('stMissing');
        const fromMissing = Math.max(0, glTarget - fromTotal);
        const newMissing  = Math.max(0, glTarget - newTotal);
        animateNumber(fromMissing, newMissing, 700, v => { elMissing.textContent = fmtEur(v); });

        // Radial: dashoffset & Prozent-Zahl animieren
        const radial = document.getElementById('radialFill');
        radial.setAttribute('stroke-dasharray', circ);
        const elPct = document.getElementById('radialPct');
        animateNumber(fromPct, newPct, 800, v => {
            radial.setAttribute('stroke-dashoffset', circ * (1 - v/100));
            elPct.textContent = fmtNum(v, 1) + ' %';
        });

        // Merken für nächste Aktualisierung
        prevGlTotal = newTotal;
        prevGlPct   = newPct;

        // Konfetti beim erstmaligen Erreichen von 100 % (nicht bei Initial-Load / Ziel-Wechsel)
        const isComplete = newTarget > 0 && newTotal >= newTarget;
        if(isComplete && !prevWasComplete && !goalChanged && !isInitialLoad){
            setTimeout(()=>fireConfetti({count:220, duration:3000}), 250);
        }
        prevWasComplete = isComplete;

        chartData=await apiCall('/api/stats/savings-progress')||[];
        renderSparzielChart();
    }catch(e){showToast('Sparziel laden fehlgeschlagen',true);console.error(e);}
}
async function saveSparziel(){
    const n=document.getElementById('sgName').value.trim();
    const t=parseFloat(document.getElementById('sgTarget').value);
    if(!n||isNaN(t)){showToast('Felder fehlen',true);haptic('error');return;}
    try{
        await apiCall('/api/savings-goal/'+glGoalId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,target_amount:t})});
        document.getElementById('heroEdit').classList.remove('open');
        haptic('success');
        showToast('Aktualisiert');
        await loadSparziel();
    }catch(e){showToast('Fehler',true);haptic('error');}
}
function renderSparzielChart(){
    try{
        const ctx=document.getElementById('chartSavings').getContext('2d');
        if(chartSavings)chartSavings.destroy();
        const isDark=document.documentElement.getAttribute('data-theme')==='dark';
        const tick=isDark?'#a0a5b0':'#666';
        chartSavings=new Chart(ctx,{
            type:'line',
            data:{labels:chartData.map(x=>fmtDate(x.date)),datasets:[{data:chartData.map(x=>Number(x.cumulative||0)),borderColor:'#22c55e',backgroundColor:'rgba(34,197,94,0.12)',fill:true,tension:0.3,pointRadius:2,borderWidth:2}]},
            options:{responsive:true,maintainAspectRatio:false,
                plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>' '+fmtEur(c.parsed.y)}}},
                scales:{x:{display:false},y:{beginAtZero:true,ticks:{color:tick,font:{size:10},callback:v=>fmtEur(v)},grid:{color:isDark?'#2a2e37':'#f0f0f0'}}}
            }
        });
    }catch(e){console.error(e);}
}

// v1.15.1: Muss synchron zur Backend-Funktion _milestones_at() bleiben.
//   increase → Meilenstein zaehlt bei cv >= schwelle (auf-der-Schwelle = erreicht)
//   decrease → Meilenstein zaehlt erst bei cv <  schwelle (strikt drunter)
// eps kompensiert Fliesskomma-Rauschen (analog zum Backend).
function nextMilestone(a){
    const s=Number(a.start_value||0),i=Number(a.threshold_increment||1)||1,c=Number(a.current_value||0);
    const eps=i*1e-6;
    if(a.direction==='decrease'){
        // strikt-drunter-Semantik: bei c==s-i sind noch 0 Meilensteine erreicht
        const done=Math.max(0,Math.floor((s-c-eps)/i));
        return s-(done+1)*i;
    }
    const done=Math.max(0,Math.floor((c-s+eps)/i));
    return s+(done+1)*i;
}
function achProgress(a){
    const s=Number(a.start_value||0),c=Number(a.current_value||0),i=Number(a.threshold_increment||1)||1;
    const t=a.target_value==null?null:Number(a.target_value);
    if(t!=null){if(a.direction==='decrease')return pct(s-c,(s-t)||1);return pct(c-s,(t-s)||1);}
    if(a.direction==='decrease'){const p=((s-c)%i+i)%i;return pct(p,i);}
    const p=((c-s)%i+i)%i;return pct(p,i);
}
const ACH_COLORS=['green','blue','purple','orange','teal','pink'];
function achColor(i){return ACH_COLORS[i%ACH_COLORS.length];}
function colorHex(name){return{green:'#22c55e',blue:'#3b82f6',purple:'#8b5cf6',orange:'#f59e0b',teal:'#14b8a6',pink:'#ec4899',red:'#ef4444'}[name]||'#22c55e';}

async function loadAchievements(){
    try{achData=await apiCall('/api/achievements')||[];loadErrors.ach=false;renderAchievements();}
    catch(e){loadErrors.ach=true;renderAchievements();showToast('Achievements laden fehlgeschlagen',true);console.error(e);}
}
function renderAchievements(){
    const g=document.getElementById('achGrid');
    if(loadErrors.ach){g.innerHTML='<div class="retry-empty">Laden fehlgeschlagen.<br><button onclick="loadAchievements()">Nochmal versuchen</button></div>';return;}
    if(!achData.length){g.innerHTML='<div class="retry-empty">Noch keine Achievements.</div>';return;}
    g.innerHTML=achData.map((a,i)=>{
        const p=achProgress(a),c=achColor(i),nm=nextMilestone(a),cv=Number(a.current_value||0),isDone=a.is_completed;
        const tgt=a.target_value==null?null:Number(a.target_value);
        const valStr=fmtNum(cv,cv%1?2:0),nmStr=fmtNum(nm,nm%1?2:0);
        return `<div class="ach-card${isDone?' done':''}" id="achCard_${a.id}">
            ${isDone?'<span class="ach-badge">✓ Erreicht</span>':''}
            <div class="ach-head"><span class="drag-handle" title="Ziehen zum Sortieren">⠿</span><div class="ach-title">${esc(a.title)}</div><div class="ach-reward-pill">+${fmtEur(a.reward_amount)}</div></div>
            <div class="ach-value">${valStr}<small>${esc(a.unit||'')}</small>${tgt!=null?` <span class="target">/ ${fmtNum(tgt)}</span>`:''}</div>
            <div class="ach-next">Nächster Meilenstein: ${nmStr} ${esc(a.unit||'')}</div>
            <div class="ach-bar"><div class="ach-bar-fill" style="width:${p}%;background:linear-gradient(90deg,${colorHex(c)}dd,${colorHex(c)})"></div></div>
            <div class="ach-actions">
                <button class="ach-btn-plus" data-ach-id="${a.id}" onclick="milestonePlus(${a.id})" title="Kurz tippen: +${fmtNum(a.step_amount||a.threshold_increment)} · Lang halten: Datum wählen · Nächster Meilenstein alle ${fmtNum(a.threshold_increment)}">+${fmtNum(a.step_amount||a.threshold_increment)} ${esc(a.unit||'')}</button>
                <input type="number" step="0.01" class="ach-inline-input" id="achInput_${a.id}" placeholder="Wert" title="Wert setzen">
                <button class="ach-btn-set" onclick="updateAchievement(${a.id})" title="Wert übernehmen">Setzen</button>
                <button class="ach-btn-more" onclick="toggleAchExpand(${a.id})" title="Mehr">⋮</button>
            </div>
            <div class="ach-expand" id="achExpand_${a.id}">
                <div class="ach-expand-actions"><button onclick="toggleAchEdit(${a.id})">Bearbeiten</button><button onclick="openMilestoneModal(${a.id})">Backdate…</button><button onclick="resetAchievement(${a.id})">Reset</button><button class="danger" onclick="deleteAchievement(${a.id})">Löschen</button></div>
                <div class="ach-edit-form" id="achEdit_${a.id}">${editFormHTML(a)}</div>
            </div>
        </div>`;
    }).join('');
    // Long-Press auf +X-Buttons für Backdate
    document.querySelectorAll('.ach-btn-plus').forEach(btn => {
        let pressTimer=null; let triggered=false;
        const start = () => {
            triggered=false;
            pressTimer = setTimeout(() => {
                triggered=true;
                haptic([30,60,30]);
                const id = parseInt(btn.dataset.achId, 10);
                openMilestoneModal(id);
            }, 500);
        };
        const cancel = () => { clearTimeout(pressTimer); };
        btn.addEventListener('touchstart', start, {passive:true});
        btn.addEventListener('touchend', cancel);
        btn.addEventListener('touchmove', cancel);
        btn.addEventListener('touchcancel', cancel);
        btn.addEventListener('mousedown', start);
        btn.addEventListener('mouseup', cancel);
        btn.addEventListener('mouseleave', cancel);
        btn.addEventListener('click', (e) => { if(triggered){ e.preventDefault(); e.stopPropagation(); }}, true);
    });
}
function editFormHTML(a){
    const stepVal = a.step_amount!=null ? a.step_amount : a.threshold_increment;
    return `<label>Titel</label><input id="ef_title_${a.id}" value="${esc(a.title||'')}">
        <div class="grid2"><div><label>Belohnung (€)</label><input id="ef_reward_${a.id}" type="number" step="0.01" value="${a.reward_amount||''}"></div><div><label>Einheit</label><input id="ef_unit_${a.id}" value="${esc(a.unit||'')}"></div></div>
        <div class="grid2"><div><label>Startwert</label><input id="ef_start_${a.id}" type="number" step="0.01" value="${a.start_value||''}"></div><div><label>Meilenstein alle</label><input id="ef_incr_${a.id}" type="number" step="0.01" value="${a.threshold_increment||''}" title="Auszahlung nach jeder x-ten Einheit"></div></div>
        <div class="grid2"><div><label>Klick-Schritt</label><input id="ef_step_${a.id}" type="number" step="0.01" value="${stepVal||''}" title="Wert, den der grüne +Button hinzufügt"></div><div><label>Zielwert</label><input id="ef_target_${a.id}" type="number" step="0.01" value="${a.target_value==null?'':a.target_value}"></div></div>
        <div class="grid2"><div><label>Richtung</label><select id="ef_dir_${a.id}"><option value="increase" ${a.direction==='increase'?'selected':''}>Steigend</option><option value="decrease" ${a.direction==='decrease'?'selected':''}>Fallend</option></select></div><div></div></div>
        <div class="save-btns"><button class="save" onclick="saveAchEdit(${a.id})">Speichern</button><button class="cancel" onclick="toggleAchEdit(${a.id})">Abbrechen</button></div>`;
}
function toggleAchExpand(id){document.getElementById('achExpand_'+id).classList.toggle('open');}
function toggleAchEdit(id){document.getElementById('achEdit_'+id).classList.toggle('open');}

async function saveAchEdit(id){
    const b={title:document.getElementById('ef_title_'+id).value.trim(),reward_amount:parseFloat(document.getElementById('ef_reward_'+id).value),unit:document.getElementById('ef_unit_'+id).value.trim(),start_value:parseFloat(document.getElementById('ef_start_'+id).value),threshold_increment:parseFloat(document.getElementById('ef_incr_'+id).value),direction:document.getElementById('ef_dir_'+id).value};
    const stepEl=document.getElementById('ef_step_'+id);
    if(stepEl && stepEl.value!==''){
        const sv=parseFloat(stepEl.value);
        if(!isNaN(sv) && sv>0) b.step_amount=sv;
    }
    const tv=document.getElementById('ef_target_'+id).value;b.target_value=tv===''?null:parseFloat(tv);
    try{await apiCall('/api/achievements/'+id+'/edit',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});haptic('success');showToast('Aktualisiert');await Promise.all([loadAchievements(),loadSparziel()]);}
    catch(e){haptic('error');showToast(e.message||'Bearbeiten fehlgeschlagen',true);}
}
async function milestonePlus(id){
    const a=achData.find(x=>x.id==id);if(!a)return;
    const step=Number(a.step_amount||a.threshold_increment||1);
    const nv=Number(a.current_value||0)+(a.direction==='decrease'?-step:step);
    const card=document.getElementById('achCard_'+id);
    if(card){card.classList.remove('pulsing');void card.offsetWidth;card.classList.add('pulsing');}
    haptic('tap');
    try{
        await apiCall('/api/achievements/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_value:nv})});
        haptic('success');
        showToast('+'+fmtNum(step)+' '+(a.unit||''));
        await Promise.all([loadAchievements(),loadSparziel()]);
    }catch(e){haptic('error');showToast('Fehler',true);}
}
async function updateAchievement(id){
    const v=document.getElementById('achInput_'+id).value;if(v===''||v==null)return;
    try{await apiCall('/api/achievements/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_value:Number(v)})});haptic('success');showToast('Wert gesetzt');await Promise.all([loadAchievements(),loadSparziel()]);}
    catch(e){haptic('error');showToast('Update fehlgeschlagen',true);}
}

// Milestone-Backdate-Modal
function openMilestoneModal(id){
    const a=achData.find(x=>x.id==id);
    if(!a)return;
    msTargetId=id;
    document.getElementById('msModalTitle').textContent='Meilenstein: '+a.title;
    const nm=nextMilestone(a);
    document.getElementById('msModalSub').textContent=
        `Aktuell ${fmtNum(a.current_value)} ${a.unit||''}. Nächster Meilenstein bei ${fmtNum(nm)} ${a.unit||''}.`;
    document.getElementById('msDate').value=todayIso();
    document.getElementById('msDate').max=todayIso();
    document.getElementById('msValue').value='';
    document.getElementById('msValue').placeholder='Standard: +'+fmtNum(a.step_amount||a.threshold_increment)+' '+(a.unit||'');
    document.getElementById('msNote').value='';
    document.getElementById('milestoneModal').classList.add('open');
}
function closeMilestoneModal(){
    document.getElementById('milestoneModal').classList.remove('open');
    msTargetId=null;
}
async function submitMilestone(){
    if(msTargetId==null)return;
    const a=achData.find(x=>x.id==msTargetId);
    if(!a)return;
    const dateStr=document.getElementById('msDate').value||todayIso();
    const rawVal=document.getElementById('msValue').value;
    let nv;
    if(rawVal!==''){
        nv=Number(rawVal);
    } else {
        const step=Number(a.step_amount||a.threshold_increment||1);
        nv=Number(a.current_value||0)+(a.direction==='decrease'?-step:step);
    }
    const noteVal=(document.getElementById('msNote').value||'').trim();
    const card=document.getElementById('achCard_'+msTargetId);
    if(card){card.classList.remove('pulsing');void card.offsetWidth;card.classList.add('pulsing');}
    try{
        await apiCall('/api/achievements/'+msTargetId,{
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({current_value:nv, achieved_at:dateStr, note:noteVal||null})
        });
        haptic('success');
        showToast('Meilenstein hinzugefügt');
        closeMilestoneModal();
        await Promise.all([loadAchievements(),loadSparziel()]);
    }catch(e){
        haptic('error');
        showToast(e.message||'Fehler',true);
    }
}

async function createAchievement(){
    const t=document.getElementById('achTitle').value.trim(),r=parseFloat(document.getElementById('achReward').value),u=document.getElementById('achUnit').value.trim(),s=parseFloat(document.getElementById('achStart').value)||0,inc=parseFloat(document.getElementById('achIncr').value);
    const stepRaw=document.getElementById('achStep').value;
    const stepVal=stepRaw===''?null:parseFloat(stepRaw);
    const tv=document.getElementById('achTarget').value,tg=tv===''?null:parseFloat(tv),d=document.getElementById('achDir').value;
    if(!t||isNaN(r)||!u||isNaN(inc)||inc<=0){showToast('Felder ausfüllen (Meilenstein-Schwelle > 0)',true);haptic('error');return;}
    if(stepVal!==null && (isNaN(stepVal)||stepVal<=0)){showToast('Klick-Schritt muss > 0 sein (oder leer lassen)',true);haptic('error');return;}
    const body={title:t,reward_amount:r,unit:u,start_value:s,threshold_increment:inc,target_value:tg,direction:d};
    if(stepVal!==null) body.step_amount=stepVal;
    try{
        await apiCall('/api/achievements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        ['achTitle','achReward','achUnit','achStart','achIncr','achStep','achTarget'].forEach(x=>document.getElementById(x).value='');
        document.querySelectorAll('.preset-btn').forEach(b=>b.classList.remove('sel'));
        document.getElementById('achForm').classList.remove('open');
        haptic('success');
        showToast('Achievement erstellt');await loadAchievements();
    }catch(e){haptic('error');showToast('Erstellung fehlgeschlagen',true);}
}
async function resetAchievement(id){
    if(!confirm('Zurücksetzen? Löscht alle Meilensteine und Sparbeiträge für dieses Achievement.'))return;
    try{const r=await apiCall('/api/achievements/'+id+'/reset',{method:'POST'});const s=r&&r.removed_count?` (${r.removed_count} Einträge, ${fmtEur(r.removed_sum||0)} entfernt)`:'';haptic('success');showToast('Zurückgesetzt'+s);await Promise.all([loadAchievements(),loadSparziel()]);}
    catch(e){haptic('error');showToast('Reset fehlgeschlagen',true);}
}
function deleteAchievement(id){
    const a=achData.find(x=>x.id==id);
    const card=document.getElementById('achCard_'+id);
    if(card)card.classList.add('pending-delete');
    haptic('tap');
    showUndoToast(`Achievement "${a?.title||''}" löschen…`,
        ()=>{if(card)card.classList.remove('pending-delete');},
        async()=>{
            try{const r=await apiCall('/api/achievements/'+id,{method:'DELETE'});
                const s=r&&r.removed_count?` (${r.removed_count} Einträge, ${fmtEur(r.removed_sum||0)})`:'';
                haptic('success');
                showToast('Gelöscht'+s);
                await Promise.all([loadAchievements(),loadSparziel()]);
            }catch(e){haptic('error');showToast('Löschen fehlgeschlagen',true);await loadAchievements();}
        }
    );
}

const PRESETS={
    meilenstein:{achReward:'3',achUnit:'x',achStart:'0',achIncr:'1',achStep:'1',achTarget:'',achDir:'increase'},
    wert:{achReward:'5',achUnit:'',achStart:'0',achIncr:'',achStep:'',achTarget:'',achDir:'increase'},
    abnehmend:{achReward:'7',achUnit:'kg',achStart:'',achIncr:'5',achStep:'1',achTarget:'',achDir:'decrease'}
};

async function loadProgressGoals(){
    try{pgData=await apiCall('/api/progress-goals')||[];loadErrors.pg=false;renderProgressGoals();}
    catch(e){loadErrors.pg=true;renderProgressGoals();showToast('Wochenziele laden fehlgeschlagen',true);console.error(e);}
}
function renderProgressGoals(){
    const l=document.getElementById('pgList');
    if(loadErrors.pg){l.innerHTML='<div class="retry-empty">Laden fehlgeschlagen.<br><button onclick="loadProgressGoals()">Nochmal versuchen</button></div>';return;}
    if(!pgData.length){l.innerHTML='<div class="retry-empty">Noch keine Wochenziele.</div>';return;}
    l.innerHTML=pgData.map(g=>{
        const c=Number(g.current_count||0),t=Number(g.target_count||1)||1,d=c>=t,p=pct(c,t);
        const rhythmLabel=g.rhythm_type==='monthly'?'Monatlich':'Wöchentlich';
        const periodLabel=g.rhythm_type==='monthly'?'diesen Monat':'diese Woche';
        const dots=Array.from({length:t},(_,i)=>`<div class="pg-dot${i<c?' filled':''}"></div>`).join('');
        const streak=Number(g.streak||0);
        const bonusAmt=Number(g.streak_bonus_amount||0);
        const bonusN=Number(g.streak_bonus_threshold||0);
        let streakRow='';
        if(bonusAmt>0 && bonusN>0){
            const progressInCycle = streak % bonusN;
            const goldDots=Array.from({length:bonusN},(_,i)=>`<div class="pg-gold-dot${i<progressInCycle?' filled':''}"></div>`).join('');
            streakRow=`<div class="pg-streak-row">
                <span class="lbl">Bonus-Fortschritt</span>
                <div class="gold-dots">${goldDots}</div>
                <span class="bonus">+${fmtEur(bonusAmt)} bei ${bonusN}×</span>
            </div>`;
        }
        return `<div class="pg-card${d?' done':''}" id="pgCard_${g.id}">
            <div class="pg-head"><span class="drag-handle" title="Ziehen zum Sortieren">⠿</span><div class="pg-title">${esc(g.title)}</div><div class="pg-meta-right">${streak>0?`<span class="pg-streak">🔥 ${streak}${g.rhythm_type==='monthly'?'M':'W'}</span>`:''}<span class="pg-reward-pill">+${fmtEur(g.reward_amount)}</span></div></div>
            <div class="pg-value"><strong>${c}</strong> / ${t} ${periodLabel} <span class="muted" style="font-size:0.75rem">· ${rhythmLabel}</span></div>
            <div class="pg-dots">${dots}</div>
            <div class="pg-bar"><div class="pg-bar-fill ${d?'g':'b'}" style="width:${p}%"></div></div>
            ${streakRow}
            <div class="pg-actions"><button class="pg-btn-ci" onclick="checkinProgress(${g.id})">${d?'✓ Nochmal':'Check-in'}</button><button class="pg-btn-undo" onclick="checkoutProgress(${g.id})">Rückgängig</button><button class="pg-btn-more" onclick="togglePgExpand(${g.id})">⋮</button></div>
            <div class="pg-expand" id="pgExpand_${g.id}">
                <label>Titel</label><input id="pge_title_${g.id}" value="${esc(g.title||'')}">
                <div class="grid2">
                    <div><label>Belohnung (€)</label><input id="pge_reward_${g.id}" type="number" step="0.01" value="${g.reward_amount||''}"></div>
                    <div><label>Ziel-Anzahl</label><input id="pge_target_${g.id}" type="number" value="${g.target_count||''}"></div>
                </div>
                <div class="grid2">
                    <div><label>Rhythmus</label><select id="pge_rhythm_${g.id}"><option value="weekly" ${g.rhythm_type!=='monthly'?'selected':''}>Wöchentlich</option><option value="monthly" ${g.rhythm_type==='monthly'?'selected':''}>Monatlich</option></select></div>
                    <div></div>
                </div>
                <div class="grid2">
                    <div><label>Streak-Bonus alle N (0=aus)</label><input id="pge_streakN_${g.id}" type="number" min="0" value="${bonusN||''}"></div>
                    <div><label>Streak-Bonus €</label><input id="pge_streakAmt_${g.id}" type="number" step="0.01" value="${bonusAmt||''}"></div>
                </div>
                <div class="pg-expand-actions">
                    <button class="save" onclick="savePgEdit(${g.id})">Speichern</button>
                    <button class="danger" onclick="deleteProgress(${g.id})">Löschen</button>
                    <button class="cancel" onclick="togglePgExpand(${g.id})">Schließen</button>
                </div>
                <div class="pg-history" id="pgHist_${g.id}"><h4>Vergangene Perioden</h4><div class="muted" style="font-size:0.75rem;padding:0.375rem 0">Lade…</div></div>
            </div>
        </div>`;
    }).join('');
}
async function togglePgExpand(id){
    const el=document.getElementById('pgExpand_'+id);
    el.classList.toggle('open');
    if(el.classList.contains('open')) await loadPgHistory(id);
}
async function loadPgHistory(id){
    try{
        const rows=await apiCall('/api/progress-goals/'+id+'/history?limit=8')||[];
        const box=document.getElementById('pgHist_'+id);
        if(!box)return;
        const g=pgData.find(x=>x.id==id);
        const isMonthly=g&&g.rhythm_type==='monthly';
        if(!rows.length){box.innerHTML='<h4>Vergangene Perioden</h4><div class="muted" style="font-size:0.75rem;padding:0.375rem 0">Noch keine.</div>';return;}
        box.innerHTML='<h4>Vergangene Perioden</h4>'+rows.map(r=>{
            let label;
            if(isMonthly){
                const dt=new Date(r.start);
                label=dt.toLocaleDateString('de-DE',{month:'long',year:'numeric'});
            } else {
                const s=fmtShortDate(r.start),e=fmtShortDate(r.end);
                const w=r.period_key.split('-W')[1];
                label=`KW ${parseInt(w,10)} · ${s} – ${e}`;
            }
            const countCls=r.fulfilled?'done':'';
            const canBackdate=!r.is_current;
            const paid=r.paid_out?'<span class="pg-hist-paid">✓ €</span>':'';
            return `<div class="pg-hist-row${r.is_current?' current':''}">
                <span class="pg-hist-period">${label}${r.is_current?' <span class="muted">(aktuell)</span>':''}</span>
                <span class="pg-hist-count ${countCls}">${r.current_count} / ${r.target_count}</span>
                ${paid}
                ${canBackdate?`<button class="pg-hist-add" onclick="backdateToPeriod(${id},'${r.start}')">+1</button>`:''}
            </div>`;
        }).join('');
    }catch(e){const box=document.getElementById('pgHist_'+id);if(box)box.innerHTML='<h4>Vergangene Perioden</h4><div class="muted">Fehler beim Laden.</div>';}
}
async function backdateToPeriod(id,startDate){
    try{
        await apiCall('/api/progress-goals/'+id+'/checkin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({log_date:startDate})});
        haptic('success');
        showToast('Nachgetragen');
        await Promise.all([loadProgressGoals(),loadSparziel(),loadPgHistory(id)]);
    }catch(e){haptic('error');showToast(e.message||'Fehler',true);}
}
async function savePgEdit(id){
    const b={
        title:document.getElementById('pge_title_'+id).value.trim(),
        reward_amount:parseFloat(document.getElementById('pge_reward_'+id).value),
        target_count:parseInt(document.getElementById('pge_target_'+id).value,10),
        rhythm_type:document.getElementById('pge_rhythm_'+id).value,
        streak_bonus_threshold:parseInt(document.getElementById('pge_streakN_'+id).value,10)||0,
        streak_bonus_amount:parseFloat(document.getElementById('pge_streakAmt_'+id).value)||0
    };
    try{await apiCall('/api/progress-goals/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});haptic('success');showToast('Aktualisiert');await loadProgressGoals();}
    catch(e){haptic('error');showToast('Fehler',true);}
}
async function checkinProgress(id){
    try{
        const r=await apiCall('/api/progress-goals/'+id+'/checkin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
        let msg='Check-in!';
        if(r&&r.streak_bonus_paid){msg='🎉 Streak-Bonus ausgezahlt!';haptic('success');}
        else if(r&&r.paid_out){msg='Check-in! Belohnung ausgezahlt';haptic('success');}
        else haptic('tap');
        showToast(msg);
        await Promise.all([loadProgressGoals(),loadSparziel()]);
    }catch(e){haptic('error');showToast('Check-in fehlgeschlagen',true);}
}
async function checkoutProgress(id){
    try{await apiCall('/api/progress-goals/'+id+'/checkout',{method:'DELETE'});haptic('tap');showToast('Rückgängig');await Promise.all([loadProgressGoals(),loadSparziel()]);}
    catch(e){haptic('error');showToast(e.message||'Fehler',true);}
}
async function createProgressGoal(){
    const t=document.getElementById('pgTitle').value.trim();
    const r=parseFloat(document.getElementById('pgReward').value);
    const rt=document.getElementById('pgRhythm').value;
    const tg=parseInt(document.getElementById('pgTarget').value,10);
    const sn=parseInt(document.getElementById('pgStreakN').value,10)||0;
    const sa=parseFloat(document.getElementById('pgStreakAmt').value)||0;
    if(!t||isNaN(r)||!tg){showToast('Felder ausfüllen',true);haptic('error');return;}
    try{
        await apiCall('/api/progress-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,reward_amount:r,rhythm_type:rt,target_count:tg,streak_bonus_amount:sa,streak_bonus_threshold:sn})});
        ['pgTitle','pgReward','pgTarget','pgStreakN','pgStreakAmt'].forEach(x=>document.getElementById(x).value='');
        document.getElementById('pgForm').classList.remove('open');
        haptic('success');
        showToast('Wochenziel erstellt');await loadProgressGoals();
    }catch(e){haptic('error');showToast('Erstellung fehlgeschlagen',true);}
}
function deleteProgress(id){
    const g=pgData.find(x=>x.id==id);
    const card=document.getElementById('pgCard_'+id);
    if(card)card.classList.add('pending-delete');
    haptic('tap');
    showUndoToast(`Wochenziel "${g?.title||''}" löschen…`,
        ()=>{if(card)card.classList.remove('pending-delete');},
        async()=>{
            try{const r=await apiCall('/api/progress-goals/'+id,{method:'DELETE'});
                const s=r&&r.removed_count?` (${r.removed_count} Einträge, ${fmtEur(r.removed_sum||0)})`:'';
                haptic('success');
                showToast('Gelöscht'+s);
                await Promise.all([loadProgressGoals(),loadSparziel()]);
            }catch(e){haptic('error');showToast('Löschen fehlgeschlagen',true);await loadProgressGoals();}
        }
    );
}

async function loadSavingsGoals(){
    try{
        const list=await apiCall('/api/savings-goals')||[];
        const box=document.getElementById('sgList');
        if(!box)return;
        if(!list.length){box.innerHTML='<div class="muted" style="padding:0.5rem;font-size:0.8125rem">Noch keine Sparziele.</div>';return;}
        box.innerHTML=list.map(g=>{
            const saved=Number(g.saved_amount||0);
            const target=Number(g.target_amount||0);
            const p=target>0?Math.min(100,(saved/target)*100):0;
            const active=!!g.is_active;
            return `<div class="ach-card" style="${active?'border-color:var(--green);background:var(--green-bg)':''}">
                <div class="ach-head">
                    <div class="ach-title">${active?'⭐ ':''}${esc(g.name)}</div>
                    <div class="ach-reward-pill">${active?'Aktiv':'Pausiert'}</div>
                </div>
                <div class="ach-value">${fmtEur(saved)} <small>/ ${fmtEur(target)}</small></div>
                <div class="ach-bar"><div class="ach-bar-fill" style="width:${p}%;background:linear-gradient(90deg,#16a34a,#22c55e)"></div></div>
                <div style="display:flex;gap:6px;margin-top:0.375rem;flex-wrap:wrap">
                    ${active?'':`<button onclick="activateSavingsGoal(${g.id})" style="flex:1;padding:0.4375rem;font-size:0.75rem;background:var(--green);color:#fff;border:none;border-radius:6px;font-weight:600;cursor:pointer;margin:0">Aktivieren</button>`}
                    <button onclick="deleteSavingsGoal(${g.id},'${esc(g.name).replace(/'/g,"\\'")}')" style="padding:0.4375rem 0.75rem;font-size:0.75rem;background:var(--red-bg);color:var(--red);border:none;border-radius:6px;font-weight:600;cursor:pointer;margin:0" ${active&&list.length===1?'disabled':''}>Löschen</button>
                </div>
            </div>`;
        }).join('');
    }catch(e){console.error(e);}
}
async function createSavingsGoal(){
    const name=document.getElementById('sgNewName').value.trim();
    const target=parseFloat(document.getElementById('sgNewTarget').value);
    const activate=document.getElementById('sgNewActivate').checked;
    if(!name||isNaN(target)||target<=0){showToast('Felder ausfüllen',true);haptic('error');return;}
    try{
        await apiCall('/api/savings-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,target_amount:target,activate})});
        document.getElementById('sgNewName').value='';document.getElementById('sgNewTarget').value='';
        document.getElementById('sgForm').classList.remove('open');
        haptic('success');showToast(activate?'Sparziel aktiviert':'Sparziel erstellt');
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadLog?.()]);
    }catch(e){haptic('error');showToast(e.message||'Fehler',true);}
}
async function activateSavingsGoal(id){
    try{
        await apiCall('/api/savings-goals/'+id+'/activate',{method:'POST'});
        haptic('success');showToast('Aktiviert – Kontostand des vorherigen Ziels bleibt gespeichert');
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements(),loadProgressGoals()]);
    }catch(e){haptic('error');showToast(e.message||'Fehler',true);}
}
async function deleteSavingsGoal(id,name){
    if(!confirm(`Sparziel "${name}" wirklich löschen? Alle zugehörigen Sparbeiträge werden entfernt.`))return;
    try{
        const r=await apiCall('/api/savings-goals/'+id,{method:'DELETE'});
        haptic('success');
        showToast('Gelöscht'+(r&&r.removed_sum?` (${fmtEur(r.removed_sum)} entfernt)`:''));
        await Promise.all([loadSavingsGoals(),loadSparziel()]);
    }catch(e){haptic('error');showToast(e.message||'Löschen fehlgeschlagen',true);}
}
async function loadPotentialGoals(){
    try{const d=await apiCall('/api/potential-goals')||[];document.getElementById('potList').innerHTML=d.length?d.map(p=>`<div class="li" id="potLi_${p.id}"><span>${esc(p.name)}${p.estimated_price?' — <strong>'+fmtEur(p.estimated_price)+'</strong>':''}</span><button class="li-del" onclick="deletePotential(${p.id})" title="Löschen">×</button></div>`).join(''):'<div class="muted" style="padding:0.5rem;font-size:0.8125rem">Noch keine Einträge.</div>';}catch(e){}
}

async function createPotential(){
    const n=document.getElementById('potName').value.trim(),pv=document.getElementById('potPrice').value,pr=pv===''?null:parseFloat(pv);
    if(!n){showToast('Name fehlt',true);haptic('error');return;}
    try{await apiCall('/api/potential-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,estimated_price:pr})});document.getElementById('potName').value='';document.getElementById('potPrice').value='';document.getElementById('potForm').classList.remove('open');haptic('success');await loadPotentialGoals();}
    catch(e){haptic('error');showToast('Fehler',true);}
}
function deletePotential(id){
    const li=document.getElementById('potLi_'+id);
    if(li)li.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Eintrag löschen…',
        ()=>{if(li)li.classList.remove('pending-delete');},
        async()=>{try{await apiCall('/api/potential-goals/'+id,{method:'DELETE'});haptic('success');await loadPotentialGoals();}catch(e){haptic('error');await loadPotentialGoals();}}
    );
}
async function loadFutureIdeas(){
    try{const d=await apiCall('/api/future-ideas')||[];document.getElementById('ideaList').innerHTML=d.length?d.map(i=>`<div class="li" id="ideaLi_${i.id}"><span>${esc(i.title)}${i.category?' <span class="muted">('+esc(i.category)+')</span>':''}</span><button class="li-del" onclick="deleteIdea(${i.id})">×</button></div>`).join(''):'<div class="muted" style="padding:0.5rem;font-size:0.8125rem">Noch keine Ideen.</div>';}catch(e){}
}
async function createIdea(){
    const t=document.getElementById('ideaTitle').value.trim(),c=document.getElementById('ideaCat').value.trim();
    if(!t){showToast('Titel fehlt',true);haptic('error');return;}
    try{await apiCall('/api/future-ideas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,category:c||null})});document.getElementById('ideaTitle').value='';document.getElementById('ideaCat').value='';document.getElementById('ideaForm').classList.remove('open');haptic('success');await loadFutureIdeas();}
    catch(e){haptic('error');showToast('Fehler',true);}
}
function deleteIdea(id){
    const li=document.getElementById('ideaLi_'+id);
    if(li)li.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Idee löschen…',
        ()=>{if(li)li.classList.remove('pending-delete');},
        async()=>{try{await apiCall('/api/future-ideas/'+id,{method:'DELETE'});haptic('success');await loadFutureIdeas();}catch(e){haptic('error');await loadFutureIdeas();}}
    );
}

async function loadLog(){
    try{logRaw=await apiCall('/api/activity-log?limit=500')||[];loadErrors.log=false;renderLog();}
    catch(e){loadErrors.log=true;document.getElementById('logBody').innerHTML='<div class="retry-empty">Laden fehlgeschlagen.<br><button onclick="loadLog()">Nochmal versuchen</button></div>';showToast('Log laden fehlgeschlagen',true);}
}
function filterLogRows(){
    const q=document.getElementById('logSearch').value.trim().toLowerCase();
    let rows=logRaw;
    if(logFilter!=='all')rows=rows.filter(r=>(r.type||'')===logFilter);
    if(q)rows=rows.filter(r=>(r.title||'').toLowerCase().includes(q)||(r.description||'').toLowerCase().includes(q));
    return rows;
}
function renderLog(){
    const rows=filterLogRows();
    const sum=rows.reduce((a,r)=>a+Number(r.amount||0),0);
    const sumBox=document.getElementById('logSum');
    const filtered=document.getElementById('logSearch').value.trim()||logFilter!=='all';
    if(rows.length){sumBox.style.display='flex';sumBox.innerHTML=`<span>${rows.length} Einträge${filtered?' (gefiltert)':''}</span><strong>+${fmtEur(sum)}</strong>`;}
    else{sumBox.style.display='none';}
    const body=document.getElementById('logBody');
    if(!rows.length){body.innerHTML='<div class="log-empty">Keine Einträge.</div>';return;}
    if(logView==='weekly') renderLogWeekly(rows,body); else renderLogFlat(rows,body);
}
const LOG_LABELS={initial:'Start',milestone:'Meilenstein',checkin:'Check-in',streak_bonus:'Bonus'};
function logRowHtml(r){
    const t=r.type||'initial';
    const tagCls=t==='checkin'&&r.fulfilled?'checkin fulfilled':t;
    const amt=Number(r.amount||0);
    const amtCls=t==='streak_bonus'?'log-amt gold':'log-amt';
    const amtHtml=amt>0?`<span class="${amtCls}">+${fmtEur(amt)}</span>`:'<span class="log-amt zero">—</span>';
    const note=r.note||'';
    const hasNote=!!note;
    const noteInline = hasNote
        ? `<span class="log-note-inline" onclick="openNoteModal('${t}',${r.log_id})" title="Notiz bearbeiten">${esc(note)}</span>`
        : '';
    const noteTitle = hasNote ? 'Notiz: '+note : 'Notiz hinzufügen';
    const noteBtn=`<button class="log-note-btn ${hasNote?'has-note':''}" onclick="openNoteModal('${t}',${r.log_id})" title="${esc(noteTitle)}">✎</button>`;
    const delBtn=r.deletable?`<button class="log-del" onclick="deleteLogEntry('${t}',${r.log_id})">×</button>`:'<span class="log-del disabled">×</span>';
    return `<div class="log-row ${hasNote?'has-note':''}" id="logRow_${t}_${r.log_id}"><span class="log-tag ${tagCls}">${LOG_LABELS[t]||t}</span><span class="log-title">${esc(r.title||'')}</span><span class="log-desc">${esc(r.description||'')}</span>${noteInline}${amtHtml}${noteBtn}${delBtn}</div>`;
}
function renderLogFlat(rows,body){
    const byDay={};
    rows.forEach(r=>{const d=r.date?r.date.slice(0,10):'unbekannt';(byDay[d]=byDay[d]||[]).push(r);});
    body.innerHTML=Object.keys(byDay).sort().reverse().map(day=>{
        const daySum=byDay[day].reduce((a,r)=>a+Number(r.amount||0),0);
        return `<div class="log-week"><div class="log-week-content open"><div class="log-day"><div class="log-day-hdr"><span>${fmtDay(day)}</span>${daySum>0?`<span class="day-sum">+${fmtEur(daySum)}</span>`:''}</div>${byDay[day].map(logRowHtml).join('')}</div></div></div>`;
    }).join('');
}
function renderLogWeekly(rows,body){
    const byWeek={};
    rows.forEach(r=>{
        const d=new Date(r.date);
        const {week,year}=isoWeek(d);
        const key=`${year}-W${String(week).padStart(2,'0')}`;
        if(!byWeek[key]){
            const monday=new Date(d);monday.setDate(d.getDate()-((d.getDay()||7)-1));
            const sunday=new Date(monday);sunday.setDate(monday.getDate()+6);
            byWeek[key]={rows:[],week,year,start:monday,end:sunday};
        }
        byWeek[key].rows.push(r);
    });
    const currentKey=(()=>{const w=currentWeekInfo();return `${w.year}-W${String(w.week).padStart(2,'0')}`;})();
    body.innerHTML=Object.keys(byWeek).sort().reverse().map(key=>{
        const w=byWeek[key];
        const total=w.rows.reduce((a,r)=>a+Number(r.amount||0),0);
        const isOpen=key===currentKey;
        const s=w.start.toLocaleDateString('de-DE',{day:'2-digit',month:'short'});
        const e=w.end.toLocaleDateString('de-DE',{day:'2-digit',month:'short',year:'numeric'});
        const byDay={};
        w.rows.forEach(r=>{const d=r.date?r.date.slice(0,10):'unbekannt';(byDay[d]=byDay[d]||[]).push(r);});
        const inner=Object.keys(byDay).sort().reverse().map(day=>{
            const daySum=byDay[day].reduce((a,r)=>a+Number(r.amount||0),0);
            return `<div class="log-day"><div class="log-day-hdr"><span>${fmtDay(day)}</span>${daySum>0?`<span class="day-sum">+${fmtEur(daySum)}</span>`:''}</div>${byDay[day].map(logRowHtml).join('')}</div>`;
        }).join('');
        return `<div class="log-week">
            <div class="log-week-hdr" onclick="toggleWeek('${key}')">
                <span class="week-label">KW ${w.week} · ${s} – ${e}</span>
                <span class="week-summary">${w.rows.length} Einträge</span>
                <span class="week-total">+${fmtEur(total)}</span>
            </div>
            <div class="log-week-content ${isOpen?'open':''}" id="logWeek_${key}">${inner}</div>
        </div>`;
    }).join('');
}
function toggleWeek(key){
    document.getElementById('logWeek_'+key).classList.toggle('open');
}
function deleteLogEntry(type,id){
    const row=document.getElementById(`logRow_${type}_${id}`);
    if(row)row.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Eintrag löschen…',
        ()=>{if(row)row.classList.remove('pending-delete');},
        async()=>{
            try{
                if(type==='checkin'){
                    const r=await apiCall('/api/progress-logs/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast(r&&r.payout_removed?'Gelöscht (inkl. Sparbeitrag)':'Gelöscht');
                    await Promise.all([loadLog(),loadProgressGoals(),loadSparziel()]);
                } else if(type==='milestone'){
                    const r=await apiCall('/api/achievement-logs/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast(r&&r.payout_removed?'Gelöscht (inkl. Sparbeitrag)':'Gelöscht');
                    await Promise.all([loadLog(),loadAchievements(),loadSparziel()]);
                } else if(type==='initial'||type==='streak_bonus'){
                    await apiCall('/api/savings-transactions/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast('Gelöscht');
                    await Promise.all([loadLog(),loadSparziel()]);
                }
            }catch(e){haptic('error');showToast('Löschen fehlgeschlagen',true);await loadLog();}
        }
    );
}
async function exportCsv(){
    try{const res=await apiCall('/api/savings-transactions/export',{raw:true});if(!res||!res.ok){showToast('Export fehlgeschlagen',true);return;}
        const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='vexbob-log.csv';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);}
    catch(e){showToast('Export fehlgeschlagen',true);}
}
async function downloadBackup(){
    try{
        const data=await apiCall('/api/backup');
        const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
        const url=URL.createObjectURL(blob);
        const a=document.createElement('a');
        const date=new Date().toISOString().slice(0,10);
        a.href=url;a.download=`vexbob-backup-${date}.json`;
        document.body.appendChild(a);a.click();a.remove();
        URL.revokeObjectURL(url);
        haptic('success');
        showToast('Backup heruntergeladen');
    }catch(e){haptic('error');showToast('Backup fehlgeschlagen',true);}
}

// --- Heatmap ---
async function loadHeatmap(){
    const range=parseInt(document.getElementById('hmRange').value,10)||365;
    try{
        heatmapData=await apiCall('/api/stats/heatmap?days='+range)||[];
        loadErrors.hm=false;
        renderHeatmap();
    }catch(e){
        loadErrors.hm=true;
        document.getElementById('hmGrid').innerHTML='<div class="muted" style="padding:1rem">Laden fehlgeschlagen.</div>';
    }
}
// Bestimmt den Level (0..4) für einen Tag anhand der aktiven Metrik.
// Bei "all" wird das vom Server gelieferte level verwendet.
// Bei den anderen Metriken werden Schwellen quantil-basiert aus den positiven Werten abgeleitet.
function computeMetricLevels(metric){
    if(metric==='all') return heatmapData.map(d=>d.level);
    const getVal = d => metric==='amount' ? Number(d.amount||0)
                     : metric==='checkins' ? Number(d.checkins||0)
                     : Number(d.milestones||0);
    const positives = heatmapData.map(getVal).filter(v => v>0).sort((a,b)=>a-b);
    if(!positives.length) return heatmapData.map(()=>0);
    // Quantile 25/50/75/95 -> Level 1..4
    const q = p => positives[Math.min(positives.length-1, Math.floor(positives.length*p))];
    const q1=q(0.25), q2=q(0.5), q3=q(0.75), q4=q(0.95);
    return heatmapData.map(d=>{
        const v=getVal(d);
        if(v<=0) return 0;
        if(v<=q1) return 1;
        if(v<=q2) return 2;
        if(v<=q3) return 3;
        return v<=q4 ? 4 : 4;
    });
}

function renderHeatmap(){
    const grid=document.getElementById('hmGrid');
    if(!heatmapData.length){grid.innerHTML='';document.getElementById('hmStats').innerHTML='';return;}
    const levels = computeMetricLevels(hmMetric);
    const first=new Date(heatmapData[0].date);
    const padDays=(first.getDay()||7)-1;
    const cells=[];
    for(let i=0;i<padDays;i++)cells.push(`<div class="hm-day l0" style="visibility:hidden"></div>`);
    heatmapData.forEach((d,idx)=>{
        const parts=d.date.split('-');
        const dateFmt=`${parts[2]}.${parts[1]}.${parts[0]}`;
        const tip=`${dateFmt} · ${d.checkins} Check-ins · ${d.milestones} Meilensteine · ${fmtEur(d.amount)}`;
        cells.push(`<div class="hm-day l${levels[idx]}" data-tip="${esc(tip)}" data-date="${d.date}"></div>`);
    });
    grid.innerHTML=cells.join('');

    const activeDays=heatmapData.filter(d=>d.total>0).length;
    let maxStreak=0,tmp=0,curStreak=0;
    heatmapData.forEach(d=>{if(d.total>0){tmp++;if(tmp>maxStreak)maxStreak=tmp;}else tmp=0;});
    for(let i=heatmapData.length-1;i>=0;i--){if(heatmapData[i].total>0)curStreak++;else break;}
    const totalCi=heatmapData.reduce((a,d)=>a+d.checkins,0);
    const totalMl=heatmapData.reduce((a,d)=>a+d.milestones,0);
    const totalAmt=heatmapData.reduce((a,d)=>a+d.amount,0);

    document.getElementById('hmStats').innerHTML=`
        <div class="hm-stat"><div class="lbl">Aktive Tage</div><div class="val">${activeDays}</div></div>
        <div class="hm-stat"><div class="lbl">Aktuelle Serie</div><div class="val">${curStreak} 🔥</div></div>
        <div class="hm-stat"><div class="lbl">Beste Serie</div><div class="val">${maxStreak}</div></div>
        <div class="hm-stat"><div class="lbl">Check-ins</div><div class="val">${totalCi}</div></div>
        <div class="hm-stat"><div class="lbl">Meilensteine</div><div class="val">${totalMl}</div></div>
        <div class="hm-stat"><div class="lbl">Summe</div><div class="val">${fmtEur(totalAmt)}</div></div>
    `;

    const tip=document.getElementById('hmTooltip');
    grid.querySelectorAll('.hm-day').forEach(cell=>{
        const show=()=>{
            const t=cell.getAttribute('data-tip');if(!t)return;
            tip.textContent=t;
            const rect=cell.getBoundingClientRect();
            tip.style.left=Math.min(window.innerWidth-260,rect.left)+'px';
            tip.style.top=(rect.top-32)+'px';
            tip.classList.add('show');
        };
        const hide=()=>tip.classList.remove('show');
        cell.addEventListener('mouseenter',show);
        cell.addEventListener('mouseleave',hide);
        cell.addEventListener('touchstart',(e)=>{show();},{passive:true});
        cell.addEventListener('touchend',hide);
    });
}

// --- Trophies ---
async function loadTrophies(){
    try{
        trophyData=await apiCall('/api/trophies')||[];
        loadErrors.trophies=false;
        renderTrophies();
    }catch(e){
        loadErrors.trophies=true;
        document.getElementById('trophyGrid').innerHTML='<div class="trophy-empty">Laden fehlgeschlagen.</div>';
    }
}
function renderTrophies(){
    const stats=document.getElementById('trophyStats');
    const grid=document.getElementById('trophyGrid');
    if(!trophyData.length){
        stats.innerHTML='';
        grid.innerHTML='<div class="trophy-empty">Noch keine Trophäen. Schließe dein erstes Sparziel ab, um hier deine Erfolge zu sammeln! 🏆</div>';
        return;
    }
    const total=trophyData.reduce((a,t)=>a+Number(t.final_amount||0),0);
    const withDur=trophyData.filter(t=>t.duration_days);
    const avgDays=withDur.length?Math.round(withDur.reduce((a,t)=>a+t.duration_days,0)/withDur.length):null;
    stats.innerHTML=`
        <div class="trophy-stat"><div class="lbl">Trophäen</div><div class="val">${trophyData.length}</div></div>
        <div class="trophy-stat"><div class="lbl">Insgesamt gespart</div><div class="val">${fmtEur(total)}</div></div>
        <div class="trophy-stat"><div class="lbl">Ø Dauer</div><div class="val">${avgDays!=null?avgDays+' d':'—'}</div></div>
    `;
    grid.innerHTML=trophyData.map(t=>{
        const dur=t.duration_days?`${t.duration_days} Tage`:'';
        const date=t.completed_at?new Date(t.completed_at).toLocaleDateString('de-DE',{day:'2-digit',month:'short',year:'numeric'}):'';
        return `<div class="trophy-card ${esc(t.color||'gold')}">
            <button class="trophy-del" onclick="deleteTrophy(${t.id})" title="Löschen">×</button>
            <div class="trophy-icon">${esc(t.icon||'🏆')}</div>
            <div class="trophy-name">${esc(t.name)}</div>
            <div class="trophy-amount">${fmtEur(t.final_amount)}</div>
            <div class="trophy-meta">${date}${dur?' · '+dur:''}</div>
            ${t.note?`<div class="trophy-note">"${esc(t.note)}"</div>`:''}
        </div>`;
    }).join('');
}
async function deleteTrophy(id){
    if(!confirm('Trophäe wirklich löschen?'))return;
    try{
        await apiCall('/api/trophies/'+id,{method:'DELETE'});
        haptic('success');
        showToast('Gelöscht');
        await loadTrophies();
    }catch(e){haptic('error');showToast('Fehler',true);}
}

function openCompleteModal(){
    if(!glGoalId){showToast('Kein aktives Sparziel',true);haptic('error');return;}
    document.getElementById('cmName').value=document.getElementById('goalName').textContent||'';
    document.getElementById('cmNote').value='';
    document.getElementById('cmIcon').value='🏆';
    document.getElementById('cmColor').value='gold';
    document.getElementById('completeModal').classList.add('open');
    haptic('tap');
}
function closeCompleteModal(){
    document.getElementById('completeModal').classList.remove('open');
}
async function submitComplete(){
    const name=document.getElementById('cmName').value.trim();
    if(!name){showToast('Name fehlt',true);haptic('error');return;}
    const body={
        name,
        target_amount:glTarget,
        final_amount:glTotal,
        icon:document.getElementById('cmIcon').value,
        color:document.getElementById('cmColor').value,
        note:document.getElementById('cmNote').value.trim()||null
    };
    try{
        await apiCall('/api/savings-goal/'+glGoalId+'/complete',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(body)
        });
        haptic('success');
        showToast('🏆 Trophäe verdient!');
        closeCompleteModal();
        document.getElementById('heroEdit').classList.remove('open');
        // Nach Abschluss: neues leeres Sparziel startet bei 0 → State resetten,
        // damit Radial nicht von "voll" auf 0 runter-animiert und Konfetti sauber neu triggern kann.
        prevGlTotal = null; prevGlPct = null; prevWasComplete = false;
        // Konfetti-Feuerwerk zur Feier des Abschlusses
        fireConfetti({count:260, duration:3200});
        setTimeout(()=>fireConfetti({count:140, duration:2400, originX: window.innerWidth*0.25, spread: Math.PI*0.9}), 300);
        setTimeout(()=>fireConfetti({count:140, duration:2400, originX: window.innerWidth*0.75, spread: Math.PI*0.9}), 600);
        await Promise.all([loadSparziel(),loadTrophies()]);
        activateTab('trophies');
    }catch(e){
        haptic('error');
        showToast(e.message||'Fehler',true);
    }
}

// --- Notiz-Modal für Log-Einträge ---
function openNoteModal(type, logId){
    const row = logRaw.find(x => (x.type||'initial')===type && x.log_id===logId);
    if(!row){showToast('Eintrag nicht gefunden',true);return;}
    noteTarget = {type, id: logId};
    document.getElementById('noteModalSub').textContent =
        `${LOG_LABELS[type]||type} · ${row.title||''}${row.description?' · '+row.description:''}`;
    document.getElementById('noteText').value = row.note || '';
    document.getElementById('noteModal').classList.add('open');
    setTimeout(()=>{document.getElementById('noteText').focus();}, 50);
    haptic('tap');
}
function closeNoteModal(){
    document.getElementById('noteModal').classList.remove('open');
    noteTarget = null;
}
async function submitNote(){
    if(!noteTarget) return;
    const note = document.getElementById('noteText').value.trim();
    let url;
    if(noteTarget.type==='checkin')            url = '/api/progress-logs/'+noteTarget.id+'/note';
    else if(noteTarget.type==='milestone')     url = '/api/achievement-logs/'+noteTarget.id+'/note';
    else                                       url = '/api/savings-transactions/'+noteTarget.id+'/note'; // initial, streak_bonus
    try{
        await apiCall(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({note})});
        // Lokal aktualisieren, damit Reload nicht nötig
        const row = logRaw.find(x => (x.type||'initial')===noteTarget.type && x.log_id===noteTarget.id);
        if(row) row.note = note;
        haptic('success');
        showToast(note ? 'Notiz gespeichert' : 'Notiz entfernt');
        closeNoteModal();
        renderLog();
    }catch(e){
        haptic('error');
        showToast(e.message || 'Speichern fehlgeschlagen', true);
    }
}

// Modal-Backdrop-Click
['milestoneModal','completeModal','noteModal'].forEach(id=>{
    const el=document.getElementById(id);
    if(el)el.addEventListener('click',e=>{if(e.target.id===id)el.classList.remove('open');});
});

document.getElementById('logoutBtn').addEventListener('click',()=>{clearToken();location.href='/private/login.html';});
document.getElementById('themeBtn').addEventListener('click',()=>{toggleTheme();if(chartSavings)renderSparzielChart();});
document.querySelectorAll('.tab-btn').forEach(b=>b.addEventListener('click',()=>activateTab(b.dataset.tab)));
document.querySelectorAll('.preset-btn').forEach(b=>{b.addEventListener('click',()=>{document.querySelectorAll('.preset-btn').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');const p=PRESETS[b.dataset.preset];if(!p)return;Object.keys(p).forEach(id=>{const el=document.getElementById(id);if(el)el.value=p[id];});});});
document.querySelectorAll('.log-chip').forEach(c=>c.addEventListener('click',()=>{document.querySelectorAll('.log-chip').forEach(x=>x.classList.remove('active'));c.classList.add('active');logFilter=c.dataset.filter;renderLog();}));
document.getElementById('logSearch').addEventListener('input',renderLog);
document.querySelectorAll('.log-view-toggle button').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.log-view-toggle button').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');logView=b.dataset.view;renderLog();
}));
document.getElementById('hmRange').addEventListener('change',loadHeatmap);
// Heatmap-Metrik-Toggle (Alle / Check-ins / Meilensteine / €)
(function(){
    const chips = document.querySelectorAll('#hmMetricChips .hm-chip');
    // gespeicherte Auswahl beim Boot in UI übernehmen
    chips.forEach(c => c.classList.toggle('active', c.dataset.metric === hmMetric));
    chips.forEach(c => c.addEventListener('click', () => {
        chips.forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        hmMetric = c.dataset.metric;
        try { localStorage.setItem('vex_hm_metric', hmMetric); } catch(_){}
        haptic('tap');
        renderHeatmap();
    }));
})();

let sortableAch=null, sortablePg=null;
function initSortables(){
    if(typeof Sortable==='undefined')return;
    if(!sortableAch){
        sortableAch=Sortable.create(document.getElementById('achGrid'),{
            handle:'.drag-handle', animation:150, delay:100, delayOnTouchOnly:true,
            onEnd:async()=>{
                const ids=Array.from(document.getElementById('achGrid').children)
                    .map(el=>parseInt((el.id||'').replace('achCard_',''),10))
                    .filter(x=>!isNaN(x));
                if(!ids.length)return;
                try{
                    await apiCall('/api/reorder/achievements',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:ids})});
                    achData.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id));
                    haptic('success');
                    showToast('Reihenfolge gespeichert');
                }catch(e){haptic('error');showToast('Reihenfolge speichern fehlgeschlagen',true);await loadAchievements();}
            }
        });
    }
    if(!sortablePg){
        sortablePg=Sortable.create(document.getElementById('pgList'),{
            handle:'.drag-handle', animation:150, delay:100, delayOnTouchOnly:true,
            onEnd:async()=>{
                const ids=Array.from(document.getElementById('pgList').children)
                    .map(el=>parseInt((el.id||'').replace('pgCard_',''),10))
                    .filter(x=>!isNaN(x));
                if(!ids.length)return;
                try{
                    await apiCall('/api/reorder/progress-goals',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:ids})});
                    pgData.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id));
                    haptic('success');
                    showToast('Reihenfolge gespeichert');
                }catch(e){haptic('error');showToast('Reihenfolge speichern fehlgeschlagen',true);await loadProgressGoals();}
            }
        });
    }
}

(async function boot(){
    if(!isLoggedIn()){location.href='/private/login.html';return;}
    document.body.classList.add('ready');
    if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
    try{
        const me=await fetchMe(false);
        document.getElementById('userLabel').textContent='👤 '+me.username;
    }catch(e){return;}
    const initialTab=(location.hash||'#dashboard').slice(1);
    if(['dashboard','log','heatmap','trophies','ideen'].includes(initialTab))activateTab(initialTab);
    try{await loadAll();}catch(e){showToast('Laden fehlgeschlagen',true);console.error(e);}
    initSortables();
})();
