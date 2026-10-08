/* sparziel.js — v2.19.0
 *
 * Die Seite ist in v2.19.0 neu gebaut. Was bleibt, ist jeder Aufruf an den
 * Server: dieselben Endpunkte, dieselben Felder. Neu ist, wie sie aussieht
 * und wie man sie bedient:
 *
 *   - Drei Reiter statt vier. „Heute“ ist, weswegen man die Seite öffnet:
 *     das Ziel als Tank und darunter die Wochenziele. Log und Trophäen sind
 *     beide ein Rückblick und stehen unter „Verlauf“. Alte Anker (#log,
 *     #trophies, #ideen, #dashboard) führen weiter an die richtige Stelle.
 *   - Ein Wochenziel ist eine Kachel, und die ganze Kachel ist der Knopf für
 *     den häufigen Fall: einchecken. Ändern, Verlauf und Zurücknehmen stehen
 *     klein daneben (DESIGN 6d, „eine Zeile, eine Hauptsache“). Ein
 *     versehentlicher Tipp ist mit „Rückgängig“ im Hinweis sofort zurück.
 *   - Wird dabei Geld gutgeschrieben, fliegt der Betrag sichtbar in den Tank
 *     und die Heldenzahl zählt hoch -- die Bewegung erklärt, wohin das Geld
 *     ging (DESIGN 5).
 *   - Jeder Dialog kommt aus VexModal (js/modal.js). Bis v2.18.0 standen hier
 *     vier eigene Fenster (.vex-modal) und ein Umbau, der Formulare aus der
 *     Seite in ein Fenster umhängte; keines davon sperrte den Hintergrund oder
 *     hielt den Fokus.
 *   - Keine festen Farben mehr: die Konfetti-Farben und die Balken kommen aus
 *     den Tokens, die Zeichen aus VexIkon.
 */
let chartSavings=null, chartData={}, glGoalId=null, glTarget=0, glTotal=0;
let achData=[], pgData=[], logRaw=[], logFilter='all', logView='weekly';
let trophyData=[];
let bufferInfo=null;            // v1.43.0: Puffer-Konto {id,name,saved_amount}
let loadErrors={ach:false,pg:false,log:false,trophies:false};
// v2.9.0: Kacheln, die ihren Stand aus einem anderen Modul holen.
// ``autoSources`` ist der Katalog aus dem Backend -- die Vorlage, aus der
// sich der Bearbeiten-Dialog baut. Hier steht bewusst KEINE eigene Liste der
// Quellen: ein neues Modul soll ein Eintrag im Register sein und sonst nichts.
// ``autoStatus`` ist, was die verbundenen Quellen gerade sagen, nach
// Achievement-ID abgelegt.
let autoSources=[], autoStatus={};
const pendingDeletes = new Map();
let toastTimer=null;
let savingsGoalsCache=[], potentialCache=[], ideaCache=[];

// --- Zahl-Animation & Konfetti-State ---
let prevGlTotal = null;   // vorheriger Sparbetrag (für Delta-Animation)
let prevGlPct = null;     // vorheriger Prozentwert
let prevWasComplete = false; // bereits >= 100 % erreicht?
let confettiRaf = null;   // aktuelle rAF-ID für Konfetti (Cleanup)
// Der Stand jeder Wochenziel-Kachel beim letzten Zeichnen. Die Liste wird
// nach jedem Check-in neu gezeichnet; ohne den alten Stand stünde der Ring
// sofort auf dem neuen Wert, und man sähe nicht, was sich getan hat.
const pgStand = {};

// Seit v1.98.0 liegt die Rechnung in js/ring.js -- ein Ring animiert seine
// eigene Zahl mit, und zwei Fassungen davon waeren zwei Kurven.
function animateNumber(from, to, duration, render){
    VexRing.zaehle(from, to, duration, render);
}

function ikon(name, groesse){ return window.VexIkon ? VexIkon.svg(name, groesse || 18) : ''; }
function magBewegung(){ return !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }

// --- Konfetti (Canvas, keine externe Lib) ---
// Die Farben kommen aus den Tokens: eine feste Liste hier waere die einzige
// Stelle der Seite, die das Farbschema nicht mitnimmt.
function konfettiFarben(){
    const cs = getComputedStyle(document.documentElement);
    const liste = ['--chart-1','--chart-2','--chart-3','--chart-4','--chart-5','--chart-6','--ok','--warn','--accent']
        .map(n => cs.getPropertyValue(n).trim()).filter(Boolean);
    return liste.length ? liste : ['currentColor'];
}
function fireConfetti(opts){
    opts = opts || {};
    const canvas = document.getElementById('confettiCanvas');
    if(!canvas || !magBewegung()) return;
    const dpr = window.devicePixelRatio || 1;
    const W = window.innerWidth, H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    canvas.classList.add('show');

    const colors = konfettiFarben();
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
            x: originX, y: originY,
            vx: Math.cos(angle)*speed + (Math.random()-0.5)*2,
            vy: Math.sin(angle)*speed - Math.random()*2,
            g: 0.18 + Math.random()*0.12, drag: 0.995,
            size: 5 + Math.random()*5,
            rot: Math.random()*Math.PI*2, vr: (Math.random()-0.5)*0.35,
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
            p.x += p.vx; p.y += p.vy; p.rot += p.vr;
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
                ctx.beginPath(); ctx.arc(0,0,p.size/2,0,Math.PI*2); ctx.fill();
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

/* Der Betrag fliegt von der Kachel in den Tank. Gebucht ist er da schon --
   die Bewegung zeigt nur, WOHIN das Geld ging; die Heldenzahl zählt
   gleichzeitig hoch (loadSparziel). Ohne Bewegung (reduzierte Bewegung,
   alter Browser) bleibt es beim Hochzählen. */
function belohnungFliegt(vonEl, betrag){
    const hero = document.getElementById('heroBox');
    const ziel = document.getElementById('stTotal');
    if(!vonEl || !ziel || !(betrag > 0) || !magBewegung() || !Element.prototype.animate) return;
    const a = vonEl.getBoundingClientRect(), b = ziel.getBoundingClientRect();
    const chip = document.createElement('div');
    chip.className = 'sz-flug';
    chip.setAttribute('aria-hidden', 'true');
    chip.textContent = '+' + fmtEur(betrag);
    document.body.appendChild(chip);
    const w = chip.offsetWidth, h = chip.offsetHeight;
    const x0 = Math.max(8, a.right - w - 20), y0 = a.top + a.height / 2 - h / 2;
    const x1 = b.left + b.width / 2 - w / 2, y1 = Math.max(8, b.top + b.height / 2 - h / 2);
    const bahn = chip.animate([
        { transform: `translate(${x0}px,${y0}px) scale(.6)`, opacity: 0 },
        { transform: `translate(${x0}px,${y0 - 18}px) scale(1.06)`, opacity: 1, offset: 0.18 },
        { transform: `translate(${x1}px,${y1}px) scale(.85)`, opacity: 1, offset: 0.84 },
        { transform: `translate(${x1}px,${y1}px) scale(.5)`, opacity: 0 },
    ], { duration: 950, easing: 'cubic-bezier(.2,.7,.2,1)' });
    bahn.onfinish = () => {
        chip.remove();
        if(!hero) return;
        hero.classList.remove('ist-gefuellt'); void hero.offsetWidth; hero.classList.add('ist-gefuellt');
    };
}

function showToast(m,err){
    const t=document.getElementById('toast');
    t.innerHTML=`<span>${esc(m)}</span>`;t.classList.toggle('err',!!err);t.classList.add('show');
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),2800);
}
/* Ein Hinweis mit einer Handlung daneben, die SOFORT gilt -- anders als
   showUndoToast, das das Löschen erst nach Ablauf ausführt. Ein Check-in ist
   gebucht, sobald man tippt; „Rückgängig“ nimmt ihn wieder heraus. */
function toastMitAktion(text, label, fn){
    const t=document.getElementById('toast');
    t.innerHTML=`<span>${esc(text)}</span><button type="button" class="undo-btn" data-akt>${esc(label)}</button>`;
    t.classList.remove('err');t.classList.add('show');
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),5000);
    t.querySelector('[data-akt]').addEventListener('click',()=>{
        clearTimeout(toastTimer);t.classList.remove('show');fn();
    },{once:true});
}
function showUndoToast(message, undoFn, executeFn, delayMs=5000){
    const t=document.getElementById('toast');
    const key=Symbol();
    t.innerHTML=`<span>${esc(message)}</span><button type="button" class="undo-btn" data-undo>Rückgängig</button>`;
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
function fmtDay(d){if(!d)return'';try{return new Date(d).toLocaleDateString('de-DE',{weekday:'long',day:'numeric',month:'long'});}catch(e){return d;}}
function fmtShortDate(d){if(!d)return'';try{return new Date(d).toLocaleDateString('de-DE',{day:'2-digit',month:'short'});}catch(e){return d;}}
function fmtKurz(d){try{return d.toLocaleDateString('de-DE',{day:'numeric',month:'short'});}catch(e){return '';}}
// „14.–20. Sept.“ statt „14. Sept. – 20. Sept.“: am Handy passte die lange
// Fassung neben Anzahl und Summe nicht in die Zeile.
function fmtSpanne(a,b){
    if(a.getMonth()===b.getMonth()) return a.getDate()+'.–'+fmtKurz(b);
    return fmtKurz(a)+' – '+fmtKurz(b);
}
// Das Datum in der Ortszeit. toISOString() rechnet in UTC -- kurz nach
// Mitternacht war „heute“ damit noch gestern.
function isoTag(d){const z=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate());}
function todayIso(){return isoTag(new Date());}

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
    const monday=new Date(now.getFullYear(),now.getMonth(),now.getDate()-((now.getDay()||7)-1));
    const sunday=new Date(monday.getFullYear(),monday.getMonth(),monday.getDate()+6);
    return{week,year,start:monday,end:sunday};
}
function updatePeriodLabel(){
    const w=currentWeekInfo();
    document.getElementById('pgPeriodLbl').textContent=`KW ${w.week} · ${fmtSpanne(w.start,w.end)}`;
}

/* Die Heldenzahl: ganze Euro groß, Cent und Zeichen klein daneben
   (.v-held-rest, css/style.css). */
function heldHTML(v){
    const s=fmtEur(v);
    const i=s.lastIndexOf(',');
    if(i<0) return esc(s);
    return esc(s.slice(0,i))+'<span class="v-held-rest">'+esc(s.slice(i))+'</span>';
}

function leerHTML(text, knopf, aufruf, zeichen){
    return `<div class="empty"><span class="empty-mark">${ikon(zeichen||'ziel',26)}</span>
        <p class="empty-text">${esc(text)}</p>
        ${knopf?`<button type="button" class="v-btn v-btn--sm" onclick="${aufruf}">${esc(knopf)}</button>`:''}</div>`;
}
/* Ein Ladefehler bleibt sichtbar, statt eine leere Liste zu hinterlassen --
   „Noch nichts da“ und „der Server antwortet nicht“ dürfen nicht gleich
   aussehen. */
function fehlerHTML(text, aufruf){
    return `<div class="empty is-error"><p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--sm" onclick="${aufruf}">Erneut versuchen</button></div>`;
}

// ---- Reiter ---------------------------------------------------------------
const REITER=['heute','verlauf','ziele'];
// Lesezeichen und Links aus der Zeit vor v2.19.0 landen an der neuen Stelle.
const ALTE_ANKER={dashboard:'heute',log:'verlauf',trophies:'verlauf',ideen:'ziele'};
function activateTab(t){
    t=ALTE_ANKER[t]||t;
    if(REITER.indexOf(t)<0) t='heute';
    document.querySelectorAll('.tabs .tab-btn').forEach(x=>x.classList.toggle('active',x.dataset.tab===t));
    REITER.forEach(id=>{
        const el=document.getElementById('tab-'+id);
        if(el) el.hidden = id!==t;
    });
    history.replaceState(null,'','#'+t);
    if(t==='verlauf'){loadTrophies();loadLog();}
    if(t==='ziele'){loadSavingsGoals();loadPotentialGoals();loadFutureIdeas();}
}

// ---- Dialoge ----------------------------------------------------------------
// Ein Wert fuer ein Formularfeld: leer statt "null"/"undefined".
const feldWert=(v)=>v==null?'':esc(v);
// Ein Link nach draussen, sicher geoeffnet (v2.36.0).
function linkKnopf(url,label){
    if(!url) return '';
    return `<a class="v-btn v-btn--ghost v-btn--sm sz-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ikon('extern',15)} ${esc(label||'Ansehen')}</a>`;
}
// Die Adresse ohne Schema und Pfad: „amazon.de“ statt einer halben Zeile.
function linkKurz(url){
    try{ return new URL(url).hostname.replace(/^www\./,''); }catch(e){ return ''; }
}
function dialog(titel, html, opts){
    const d=VexModal.open(esc(titel), html, opts||{});
    if(window.VexIkon) VexIkon.einsetzen(d.root);
    return d;
}
// Enter im Formular löst die Hauptsache aus, wie ein Klick auf den Knopf.
function formular(d, fn){
    const f=d.root.querySelector('[data-form]');
    if(f) f.addEventListener('submit',e=>{e.preventDefault();fn();});
}
function beiKlick(d, sel, fn){
    const el=d.root.querySelector(sel);
    if(el) el.addEventListener('click',fn);
}
// Das erste Feld bekommt den Fokus nur am Rechner -- am Handy risse das die
// Tastatur hoch und verdeckte das halbe Blatt (DESIGN 6d).
function fokusAmRechner(id){
    if(!window.matchMedia('(min-width: 721px)').matches) return;
    const el=document.getElementById(id);
    if(el) el.focus();
}

async function loadAll(){await Promise.all([loadSparziel(),loadAchievements(),loadProgressGoals(),loadSavingsGoals(),loadAutoSources()]);updatePeriodLabel();}

// ---- Die Bühne --------------------------------------------------------------
async function loadSparziel(){
    let d;
    try{ d=await apiCall('/api/savings-goal'); }
    catch(e){ buehneFehler(); console.error(e); return; }
    // v1.43.0: "kein aktives Sparziel" ist ein regulaerer Zustand -- nach dem
    // Abschliessen wird kein Platzhalter-Ziel mehr angelegt. Die Bühne zeigt
    // dann den Puffer, in den ab sofort jede Belohnung laeuft.
    bufferInfo = d.buffer || null;
    zeichneBuehne(d);
    try{ chartData=await apiCall('/api/stats/savings-progress')||{}; }
    catch(e){ chartData={}; console.error(e); }
    zeichneWoche();
    renderSparzielChart();
}

function buehneFehler(){
    document.getElementById('szMarke').textContent='Sparziel';
    document.getElementById('goalName').textContent='Konnte nicht geladen werden';
    document.getElementById('stTotal').textContent='–';
    document.getElementById('stTarget').textContent='';
    const aktion=document.getElementById('szAktion');
    aktion.innerHTML='<button type="button" class="v-btn" onclick="loadSparziel()">Erneut versuchen</button>';
    aktion.hidden=false;
}

function zeichneBuehne(d){
    const hero=document.getElementById('heroBox');
    const ring=document.getElementById('sgRing');
    const aktion=document.getElementById('szAktion');
    const puffer=Number(bufferInfo ? bufferInfo.saved_amount : 0);
    const hasGoal=!!(d.goal && d.goal.id);
    document.getElementById('stPuffer').textContent=fmtEur(puffer);
    hero.classList.toggle('ohne-ziel', !hasGoal);
    document.getElementById('szBearbeiten').hidden=!hasGoal;

    if(!hasGoal){
        glGoalId=null; glTarget=0; glTotal=0;
        prevGlTotal=null; prevGlPct=null; prevWasComplete=false;
        hero.classList.remove('ist-voll');
        document.getElementById('szMarke').textContent='Kein aktives Sparziel';
        document.getElementById('goalName').textContent='Alles läuft in den Puffer';
        document.getElementById('stTotal').innerHTML=heldHTML(puffer);
        document.getElementById('stTarget').textContent='im Puffer';
        document.getElementById('stMissing').textContent='–';
        VexRing.set(ring,{wert:0,ziel:100});
        aktion.innerHTML=`<button type="button" class="v-btn v-btn--primary" onclick="startNewGoal()">${ikon('plus',18)} Sparziel anlegen</button>`;
        aktion.hidden=false;
        return;
    }

    const g=d.goal;
    const newGoalId=g.id;
    const newTarget=Number(g.target_amount||0);
    const newTotal=Number(d.total_saved||0);
    const newPct=pct(newTotal,newTarget);
    // Bei Ziel-Wechsel (anderes Sparziel aktiviert): keine Animation, hart setzen
    const goalChanged = (glGoalId !== null && newGoalId !== glGoalId);
    const isInitialLoad = (prevGlTotal == null);
    const fromTotal = goalChanged ? newTotal : (prevGlTotal!=null ? prevGlTotal : newTotal);
    glGoalId=newGoalId; glTarget=newTarget; glTotal=newTotal;

    document.getElementById('szMarke').textContent='Sparziel';
    document.getElementById('goalName').textContent=g.name||'Sparziel';
    const elTotal=document.getElementById('stTotal');
    animateNumber(fromTotal, newTotal, 750, v => { elTotal.innerHTML = heldHTML(v); });
    const elMissing=document.getElementById('stMissing');
    animateNumber(Math.max(0,glTarget-fromTotal), Math.max(0,glTarget-newTotal), 750,
        v => { elMissing.textContent = v > 0.004 ? fmtEur(v) : 'geschafft'; });
    // Der Ring bewegt sich von selbst: .v-ring-fill traegt die Ueberblendung
    // in CSS, hier wird nur der Zielwert gesetzt.
    VexRing.set(ring,{wert:newPct,ziel:100});

    const isComplete = newTarget > 0 && newTotal >= newTarget;
    hero.classList.toggle('ist-voll', isComplete);
    document.getElementById('stTarget').textContent = isComplete
        ? 'Ziel von ' + fmtEur(newTarget) + ' erreicht'
        : 'von ' + fmtEur(newTarget) + ' · ' + fmtNum(newPct, 0) + ' %';
    // Ist das Ziel voll, gehört der Abschluss auf die Bühne -- es ist der
    // Moment, auf den die ganze Seite hinarbeitet.
    if(isComplete){
        aktion.innerHTML=`<button type="button" class="v-btn v-btn--primary" onclick="openCompleteModal()">${ikon('pokal',18)} Ziel abschließen</button>`;
        aktion.hidden=false;
    } else {
        aktion.innerHTML=''; aktion.hidden=true;
    }
    prevGlTotal=newTotal; prevGlPct=newPct;
    // Konfetti beim erstmaligen Erreichen von 100 % (nicht bei Initial-Load / Ziel-Wechsel)
    if(isComplete && !prevWasComplete && !goalChanged && !isInitialLoad){
        setTimeout(()=>fireConfetti({count:220, duration:3000}), 250);
    }
    prevWasComplete = isComplete;
}

// Was diese Woche dazukam, aus derselben Tagesreihe wie die Kurve.
function zeichneWoche(){
    const el=document.getElementById('stWoche');
    const pts=(chartData && chartData.points) || [];
    const w=currentWeekInfo(), von=isoTag(w.start), bis=isoTag(w.end);
    const summe=pts.filter(p=>String(p.date).slice(0,10)>=von && String(p.date).slice(0,10)<=bis)
                   .reduce((a,p)=>a+Number(p.added||0),0);
    el.textContent=(summe>0?'+':'')+fmtEur(summe);
    el.classList.toggle('ist-plus', summe>0);
}

async function saveSparziel(d){
    const n=document.getElementById('sgName').value.trim();
    const t=parseFloat(document.getElementById('sgTarget').value);
    if(!n||isNaN(t)){showToast('Name und Zielbetrag fehlen',true);haptic('error');return;}
    try{
        const lk=document.getElementById('sgLink');
        await apiCall('/api/savings-goal/'+glGoalId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,target_amount:t,link:lk?lk.value.trim():undefined})});
        if(d) d.close();
        haptic('success');
        showToast('Gespeichert');
        await Promise.all([loadSparziel(),loadSavingsGoals()]);
    }catch(e){showToast(e.message||'Speichern fehlgeschlagen',true);haptic('error');}
}
function dlgSparzielBearbeiten(){
    if(!glGoalId){startNewGoal();return;}
    const d=dialog('Sparziel bearbeiten',`<form data-form>
        <label for="sgName">Name</label>
        <input id="sgName" value="${esc(document.getElementById('goalName').textContent||'')}">
        <label for="sgTarget">Zielbetrag (€)</label>
        <input id="sgTarget" type="number" step="0.01" inputmode="decimal" value="${glTarget||''}">
        <label for="sgLink">Link <span class="sz-freiwillig">wo es das gibt</span></label>
        <input id="sgLink" type="url" inputmode="url" autocomplete="off" placeholder="https://…" value="${feldWert(((savingsGoalsCache||[]).find(x=>x.id===glGoalId)||{}).link)}">
        ${aufgebenZeile(glGoalId)}
        <div class="modal-fuss">
            <button type="button" class="v-btn" data-abschluss>${ikon('pokal',16)} Abschließen</button>
            <button type="submit" class="v-btn v-btn--primary">Speichern</button>
        </div>
    </form>`);
    formular(d,()=>saveSparziel(d));
    beiKlick(d,'[data-abschluss]',()=>{d.close();openCompleteModal();});
    beiKlick(d,'[data-aufgeben]',()=>{d.close();dlgAufgeben(glGoalId);});
    fokusAmRechner('sgName');
}

/* v1.76.0: Der Verlauf hat eine echte Zeitachse -- der Server liefert jeden
 * Kalendertag ab dem ersten Eintrag DIESES Ziels. Tage mit Zugang bekommen
 * einen Punkt, alle anderen keinen. */
/* Die Farbe der Kurve folgt der Theme-Stelle "Zahlen und Diagramme".
   Ohne Einstellung ist --figure gar nicht definiert, dann greift der
   Modulton -- die Identitaet bleibt also der Standard. */
function figureColor(){
    const css=(n)=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    return css('--figure') || css('--m-sparziel');
}
/* Die Flaeche unter der Linie ist derselbe Ton bei 18 % (DESIGN.md 7).
   color-mix() ginge in CSS, aber Chart.js reicht den Wert an die Leinwand
   weiter, und die kennt es nicht -- deshalb hier von Hand aus dem Hexwert. */
function figureFill(){
    const c=figureColor();
    const m=/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c);
    if(!m) return 'rgba(94,234,146,0.18)';
    let h=m[1];
    if(h.length===3) h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    const r=parseInt(h.slice(0,2),16), g=parseInt(h.slice(2,4),16), b=parseInt(h.slice(4,6),16);
    return 'rgba('+r+','+g+','+b+',0.18)';
}

/* Chart.js kommt mit ``defer`` vom CDN und kann später da sein als die
   Antwort des Servers. Bis v2.18.0 lief das Zeichnen dann in einen
   ReferenceError, und der Sparverlauf blieb leer -- ohne Meldung, denn der
   Fehler wurde gefangen. Jetzt wartet das Zeichnen auf die Bibliothek. */
function wennChart(fn){
    if(typeof Chart!=='undefined'){fn();return;}
    if(document.readyState==='complete') return;   // CDN nicht erreichbar
    window.addEventListener('load',()=>{if(typeof Chart!=='undefined')fn();},{once:true});
}

function renderSparzielChart(){
    const flaeche=document.querySelector('.sz-b-kurve-flaeche');
    if(!flaeche) return;
    const pts=(chartData && chartData.points) || [];
    const sub=document.getElementById('szKurveSub');
    let leer=flaeche.querySelector('.sz-b-kurve-leer');
    if(!pts.length){
        if(chartSavings){chartSavings.destroy();chartSavings=null;}
        if(!leer){
            leer=document.createElement('div');
            leer.className='sz-b-kurve-leer';
            flaeche.appendChild(leer);
        }
        leer.textContent='Noch kein Verlauf. Die erste Gutschrift zeichnet die Kurve.';
        sub.textContent='';
        return;
    }
    if(leer) leer.remove();
    sub.textContent='seit '+fmtKurz(new Date(String(pts[0].date).slice(0,10)+'T12:00:00'));
    wennChart(zeichneKurve);
}

function zeichneKurve(){
    try{
        const ctx=document.getElementById('chartSavings').getContext('2d');
        if(chartSavings)chartSavings.destroy();
        const cssVar=(n)=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
        const tick=cssVar('--chart-axis');
        const pts=chartData.points||[];
        const full=pts.map(x=>VexCharts.fullDay(x.date));
        const marks=pts.map(x=>Number(x.added||0)>0);
        // Am Handy ist die Kurve ein schmales Band unter den Zahlen: ohne
        // Achse links, nur ein paar Daten unten.
        const schmal=window.matchMedia('(max-width: 899px)').matches;
        chartSavings=new Chart(ctx,{
            type:'line',
            data:{labels:pts.map(x=>fmtShortDate(x.date)),datasets:[{
                data:pts.map(x=>Number(x.cumulative||0)),
                borderColor:figureColor(),backgroundColor:figureFill(),
                fill:true,tension:0.25,borderWidth:2,
                pointRadius:pts.map((x,i)=>marks[i]&&!schmal?3:0),
                pointBackgroundColor:figureColor(),
                pointBorderColor:cssVar('--surface-1'),pointBorderWidth:1.5,
                pointHoverRadius:5}]},
            options:{responsive:true,maintainAspectRatio:false,
                interaction:{mode:'index',intersect:false},
                plugins:{legend:{display:false},tooltip:{callbacks:{
                    title:VexCharts.titleFrom(full),
                    label:c=>{
                        const p=pts[c.dataIndex]||{};
                        const zu=Number(p.added||0);
                        return zu>0?[' '+fmtEur(c.parsed.y),' an dem Tag +'+fmtEur(zu)]
                                   :' '+fmtEur(c.parsed.y);
                    }}}},
                scales:{
                    x:{display:true,ticks:{color:tick,font:{size:11},maxRotation:0,
                        autoSkip:true,autoSkipPadding:18,maxTicksLimit:schmal?4:8},
                       grid:{display:false},border:{display:false}},
                    y:{display:!schmal,beginAtZero:true,
                       ticks:{color:tick,font:{size:11},maxTicksLimit:5,callback:v=>fmtEur(v)},
                       grid:{color:cssVar('--chart-grid')},border:{display:false}}}
            }
        });
    }catch(e){console.error(e);}
}

// ---- Achievements -------------------------------------------------------------
// v1.15.1: Muss synchron zur Backend-Funktion _milestones_at() bleiben.
//   increase → Meilenstein zaehlt bei cv >= schwelle (auf-der-Schwelle = erreicht)
//   decrease → Meilenstein zaehlt erst bei cv <  schwelle (strikt drunter)
// eps kompensiert Fliesskomma-Rauschen (analog zum Backend).
function nextMilestone(a){
    const s=Number(a.start_value||0),i=Number(a.threshold_increment||1)||1,c=Number(a.current_value||0);
    const eps=i*1e-6;
    if(a.direction==='decrease'){
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

async function loadAchievements(){
    try{
        // Der Stand der Quellen kommt mit demselben Ladevorgang: eine Kachel,
        // die ihren Messwert erst eine Antwort spaeter bekommt, zeichnet sich
        // zweimal -- und beim zweiten Mal springt die Zeile darunter.
        const [ziele, stand] = await Promise.all([
            apiCall('/api/achievements'),
            apiCall('/api/achievements/auto-status').catch(()=>[]),
        ]);
        achData = ziele || [];
        autoStatus = {};
        (stand||[]).forEach(z => { autoStatus[z.achievement_id] = z; });
        loadErrors.ach=false;renderAchievements();
    }
    catch(e){loadErrors.ach=true;renderAchievements();console.error(e);}
}

// Der Katalog aendert sich selten (er haengt am Bestand der anderen Module),
// wird aber fuer jeden Bearbeiten-Dialog gebraucht. Einmal laden reicht.
async function loadAutoSources(){
    try{ autoSources = await apiCall('/api/achievements/auto-sources') || []; }
    catch(e){ autoSources = []; console.error(e); }
    if(achData.length) renderAchievements();
}

/* Eine Kachel, die ihren Wert aus einem anderen Modul holt, trägt dessen Ton
   am Punkt vor der Quellzeile -- so sieht man, woher die Zahl kommt, bevor
   man die Zeile liest (DESIGN 3: der Modulton sagt die Quelle). */
const QUELL_TOENE={health:'--m-health',schach:'--m-schach',ausgaben:'--m-ausgaben',musik:'--m-musik',ernaehrung:'--m-naehrwerte'};
function quelleTon(a){
    if(!a.auto_source) return 'var(--sz-ton)';
    const q=autoSources.find(x=>x.key===a.auto_source);
    const modul=q ? q.modul : String(a.auto_source).split('.')[0];
    return QUELL_TOENE[modul] ? 'var('+QUELL_TOENE[modul]+')' : 'var(--sz-ton)';
}

function renderAchievements(){
    const g=document.getElementById('achGrid');
    if(loadErrors.ach){g.innerHTML=fehlerHTML('Die Achievements konnten nicht geladen werden.','loadAchievements()');return;}
    if(!achData.length){
        g.innerHTML=leerHTML('Noch kein Achievement. Eines zahlt bei jedem Meilenstein: alle fünf Kilo weniger, jedes zweite Buch.','Achievement anlegen','dlgNeuesAchievement()','ziel');
        return;
    }
    g.innerHTML=achData.map(achievementHTML).join('');
    // Lange halten auf „+“ öffnet das Nachtragen mit Datum.
    g.querySelectorAll('.sz-ms-plus').forEach(btn => {
        let pressTimer=null; let triggered=false;
        const start = () => {
            triggered=false;
            pressTimer = setTimeout(() => {
                triggered=true;
                haptic([30,60,30]);
                openMilestoneModal(parseInt(btn.dataset.achId, 10));
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

function achievementHTML(a){
    const st=autoStatus[a.id];
    // Ist eine Quelle verbunden und liefert sie etwas, zeigt die Kachel
    // DEREN Stand -- das ist die Zahl, die man tatsaechlich wiegt. Der
    // gebuchte Stand steckt in den Meilensteinen, nicht in der grossen Zahl.
    const live=(a.auto_source && st && st.wert!=null) ? Number(st.wert) : null;
    const view=live!=null ? Object.assign({}, a, {current_value:live}) : a;
    const p=achProgress(view),nm=nextMilestone(view),cv=Number(view.current_value||0),fertig=!!a.is_completed;
    const tgt=a.target_value==null?null:Number(a.target_value);
    const unit=esc(a.unit||'');
    const valStr=fmtNum(cv,cv%1?2:0),nmStr=fmtNum(nm,nm%1?2:0);
    const schritt=Number(a.step_amount||a.threshold_increment||1);
    const titel=esc(a.title);
    const plus = live!=null ? '' :
        `<button type="button" class="v-btn v-btn--sm sz-ms-plus" data-ach-id="${a.id}" onclick="milestonePlus(${a.id})"
                 title="Tippen: +${fmtNum(schritt)} · Halten: mit Datum nachtragen">${ikon('plus',15)}${fmtNum(schritt)} ${unit}</button>`;
    return `<div class="sz-ms${fertig?' ist-fertig':''}" id="achCard_${a.id}" style="--ms-ton:${quelleTon(a)}">
        <span class="drag-handle" title="Ziehen zum Sortieren" aria-hidden="true">${ikon('griff',16)}</span>
        <div class="sz-ms-kopf"><span class="sz-ms-titel">${titel}</span><span class="sz-betrag">+${fmtEur(a.reward_amount)}</span></div>
        <button type="button" class="v-btn v-btn--ghost v-btn--icon sz-ms-mehr" onclick="dlgAchievement(${a.id})" aria-label="Mehr zu „${titel}“">${ikon('mehr',18)}</button>
        <div class="sz-ms-wert"><strong>${valStr}</strong><span class="sz-ms-einheit">${unit}</span>${tgt!=null?`<span class="sz-ms-ziel">Ziel ${fmtNum(tgt)}</span>`:''}</div>
        ${autoQuelleHTML(a)}
        <div class="sz-ms-balken"><i style="width:${p.toFixed(1)}%"></i></div>
        <div class="sz-ms-fuss">
            ${fertig?`<span class="sz-ms-erreicht">${ikon('haken',14)} Erreicht</span>`:`<span class="sz-ms-naechster">Nächster Meilenstein bei ${nmStr} ${unit}</span>`}
            ${plus}
        </div>
        ${autoBandHTML(a)}
    </div>`;
}

// ---- Kacheln aus anderen Modulen (v2.9.0) --------------------------------
// Zwei Bausteine auf der Kachel: eine Zeile, die sagt WOHER die Zahl kommt,
// und ein Band, das erscheint, sobald ein Meilenstein faellig waere. Das Band
// ist die einzige Stelle, an der Geld fliesst -- die Quelle selbst bucht nie,
// sie liest nur.
function autoQuelleHTML(a){
    if(!a.auto_source) return '';
    const st=autoStatus[a.id];
    if(!st || st.wert==null){
        return `<div class="sz-ms-quelle ist-leer"><span>${esc(st?st.quelle_label:'Verbundene Quelle')} liefert gerade keinen Wert</span></div>`;
    }
    const stand=st.stand?' · Stand '+fmtShortDate(st.stand):'';
    return `<div class="sz-ms-quelle"><span>${esc(st.beschriftung||st.quelle_label)}${stand}</span></div>`;
}

function autoBandHTML(a){
    const st=autoStatus[a.id];
    if(!a.auto_source || !st || !st.offene_meilensteine) return '';
    const n=st.offene_meilensteine;
    const wie=n===1?'Ein Meilenstein':`${n} Meilensteine`;
    return `<div class="sz-ms-treffer">
        <div class="sz-ms-treffer-text"><strong>${wie} erreicht</strong>
            <span>${fmtNum(st.wert)} ${esc(st.einheit||a.unit||'')} · ${fmtEur(st.gutschrift)}</span></div>
        <button type="button" class="v-btn v-btn--sm" onclick="bestaetigeQuelle(${a.id})">Gutschreiben</button>
    </div>`;
}

// Die Bestaetigung schickt KEINEN Wert mit: den liest der Server noch einmal
// selbst aus der Quelle. Eine Zahl aus dem Browser waere eine Gutschrift ueber
// etwas, das in keiner Messung steht.
async function bestaetigeQuelle(id){
    const a=achData.find(x=>x.id==id), st=autoStatus[id];
    if(!a||!st)return;
    if(!await askConfirm({title:'Meilenstein gutschreiben?',
        text:`${fmtNum(st.wert)} ${st.einheit||a.unit||''} aus ${st.beschriftung||st.quelle_label}. `
            +`Das schreibt ${fmtEur(st.gutschrift)} gut und setzt den Stand der Kachel auf diesen Wert.`,
        ok:'Gutschreiben'}))return;
    const card=document.getElementById('achCard_'+id);
    try{
        await apiCall('/api/achievements/'+id+'/auto-confirm',
            {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
        haptic('success');
        belohnungFliegt(card, Number(st.gutschrift||0));
        showToast('Gutgeschrieben: '+fmtEur(st.gutschrift));
        await Promise.all([loadAchievements(),loadSparziel(),loadSavingsGoals()]);
    }catch(e){haptic('error');showToast(e.message||'Gutschrift fehlgeschlagen',true);}
}

async function pruefeQuelle(id){
    try{
        const stand=await apiCall('/api/achievements/auto-status')||[];
        autoStatus={};stand.forEach(z=>{autoStatus[z.achievement_id]=z;});
        const st=autoStatus[id];
        renderAchievements();
        haptic('tap');
        showToast(st&&st.wert!=null
            ? 'Stand: '+fmtNum(st.wert)+' '+(st.einheit||'')
            : 'Die Quelle liefert gerade keinen Wert');
    }catch(e){haptic('error');showToast('Quelle prüfen fehlgeschlagen',true);}
}

// ---- Bearbeiten: Quelle und ihre Parameter -------------------------------
// Die Felder stehen NICHT hier, sondern kommen aus dem Katalog des Backends
// (``/api/achievements/auto-sources``). Eine Quelle beschreibt ihre Parameter
// selbst, der Dialog zeichnet nur, was dasteht.
function autoEditHTML(a){
    const opts=['<option value="">Keine — Wert von Hand eintragen</option>'];
    autoSources.forEach(q=>{
        const sel=q.key===a.auto_source?' selected':'';
        opts.push(`<option value="${esc(q.key)}"${sel}>${esc(q.label)}${q.verfuegbar?'':' (noch keine Daten)'}</option>`);
    });
    return `<label for="ef_auto_${a.id}">Wert kommt aus</label>
        <select id="ef_auto_${a.id}" onchange="autoQuelleGewechselt(${a.id})">${opts.join('')}</select>
        <div class="ach-quelle-felder" id="ef_autoparams_${a.id}">${autoParamsHTML(a.id,a.auto_source,a.auto_params||{})}</div>`;
}

function autoWert(q,params,key){
    if(params && params[key]!=null && params[key]!=='') return params[key];
    const feld=(q.params||[]).find(f=>f.key===key);
    return (feld && feld.standard!=null) ? feld.standard : '';
}

function autoParamsHTML(id,key,params){
    const q=autoSources.find(x=>x.key===key);
    if(!q) return '';
    const teile=[];
    if(!q.verfuegbar && q.grund) teile.push(`<p class="sz-dlg-hinweis">${esc(q.grund)}</p>`);
    else if(q.hinweis) teile.push(`<p class="sz-dlg-hinweis">${esc(q.hinweis)}</p>`);
    (q.params||[]).forEach(feld=>{
        // ``wenn`` blendet ein Feld aus, solange ein anderes nicht passt --
        // "über wie viele Tage" hat neben "letzter Messwert" keinen Sinn.
        const gilt=!feld.wenn||Object.keys(feld.wenn).every(
            k=>String(autoWert(q,params,k))===String(feld.wenn[k]));
        if(!gilt) return;
        const jetzt=autoWert(q,params,feld.key);
        const opts=[];
        if(!feld.pflicht) opts.push(`<option value="">${esc(feld.leer_label||'Alle')}</option>`);
        (feld.optionen||[]).forEach(o=>{
            opts.push(`<option value="${esc(o.wert)}"${String(o.wert)===String(jetzt)?' selected':''}>${esc(o.label)}</option>`);
        });
        if(!(feld.optionen||[]).length && feld.pflicht) opts.push('<option value="">— nichts vorhanden —</option>');
        teile.push(`<label>${esc(feld.label)}</label>`
            +`<select data-auto-param="${esc(feld.key)}" onchange="autoParamsNeu(${id})">${opts.join('')}</select>`);
    });
    return teile.join('');
}

function autoParamsLesen(id){
    const box=document.getElementById('ef_autoparams_'+id);
    const raus={};
    if(box) box.querySelectorAll('[data-auto-param]').forEach(el=>{
        if(el.value!=='') raus[el.dataset.autoParam]=el.value;
    });
    return raus;
}
function autoQuelleGewechselt(id){
    const key=document.getElementById('ef_auto_'+id).value;
    document.getElementById('ef_autoparams_'+id).innerHTML=autoParamsHTML(id,key,{});
}
function autoParamsNeu(id){
    const key=document.getElementById('ef_auto_'+id).value;
    document.getElementById('ef_autoparams_'+id).innerHTML=
        autoParamsHTML(id,key,autoParamsLesen(id));
}

function editFormHTML(a){
    const stepVal = a.step_amount!=null ? a.step_amount : a.threshold_increment;
    const wert=(v)=>v==null?'':esc(v);
    return `<label for="ef_title_${a.id}">Titel</label><input id="ef_title_${a.id}" value="${esc(a.title||'')}">
        <div class="sz-felder">
            <div><label for="ef_reward_${a.id}">€ je Meilenstein</label><input id="ef_reward_${a.id}" type="number" step="0.01" inputmode="decimal" value="${wert(a.reward_amount)}"></div>
            <div><label for="ef_unit_${a.id}">Einheit</label><input id="ef_unit_${a.id}" value="${esc(a.unit||'')}"></div>
            <div><label for="ef_start_${a.id}">Startwert</label><input id="ef_start_${a.id}" type="number" step="0.01" inputmode="decimal" value="${wert(a.start_value)}"></div>
            <div><label for="ef_incr_${a.id}">Meilenstein alle</label><input id="ef_incr_${a.id}" type="number" step="0.01" inputmode="decimal" value="${wert(a.threshold_increment)}"></div>
            <div><label for="ef_step_${a.id}">Schritt je Tipp</label><input id="ef_step_${a.id}" type="number" step="0.01" inputmode="decimal" value="${wert(stepVal)}"></div>
            <div><label for="ef_target_${a.id}">Zielwert</label><input id="ef_target_${a.id}" type="number" step="0.01" inputmode="decimal" value="${wert(a.target_value)}" placeholder="offen"></div>
            <div><label for="ef_dir_${a.id}">Richtung</label><select id="ef_dir_${a.id}"><option value="increase" ${a.direction==='increase'?'selected':''}>Steigend</option><option value="decrease" ${a.direction==='decrease'?'selected':''}>Fallend</option></select></div>
            <div><label for="ef_rgid_${a.id}">Belohnung geht an</label><select id="ef_rgid_${a.id}">${rewardGoalOptionsHTML(a.reward_goal_id)}</select></div>
        </div>
        ${autoEditHTML(a)}`;
}

function dlgAchievement(id){
    const a=achData.find(x=>x.id==id); if(!a) return;
    const st=autoStatus[id];
    const live=!!(a.auto_source && st && st.wert!=null);
    const d=dialog(a.title,`<form data-form>
        ${live?'':`<h4 class="sz-dlg-h">Wert setzen</h4>
        <div class="sz-setzen">
            <input type="number" step="0.01" inputmode="decimal" id="achInput_${id}" placeholder="Jetzt ${fmtNum(a.current_value)} ${esc(a.unit||'')}" aria-label="Neuer Wert">
            <button type="button" class="v-btn" data-setzen>Setzen</button>
        </div>`}
        <h4 class="sz-dlg-h">Einstellungen</h4>
        ${editFormHTML(a)}
        <div class="sz-reihe">
            ${a.auto_source
                ? `<button type="button" class="v-btn v-btn--sm" data-pruefen>${ikon('uhr',15)} Quelle prüfen</button>`
                : `<button type="button" class="v-btn v-btn--sm" data-nachtragen>${ikon('kalender',15)} Mit Datum nachtragen</button>`}
            <button type="button" class="v-btn v-btn--sm" data-reset>${ikon('zurueck',15)} Zurücksetzen</button>
        </div>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell',16)} Löschen</button>
            <button type="submit" class="v-btn v-btn--primary">Speichern</button>
        </div>
    </form>`,{breit:true});
    formular(d,()=>saveAchEdit(id,d));
    beiKlick(d,'[data-setzen]',()=>updateAchievement(id,d));
    const feld=document.getElementById('achInput_'+id);
    if(feld) feld.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();updateAchievement(id,d);}});
    beiKlick(d,'[data-pruefen]',()=>pruefeQuelle(id));
    beiKlick(d,'[data-nachtragen]',()=>{d.close();openMilestoneModal(id);});
    beiKlick(d,'[data-reset]',async()=>{if(await resetAchievement(id)) d.close();});
    beiKlick(d,'[data-weg]',()=>{d.close();deleteAchievement(id);});
}

// v1.18.2: Auswahl, wohin die Belohnung fließt
function rewardGoalOptionsHTML(selectedId){
    const goals = savingsGoalsCache || [];
    // „Automatisch“ heißt: aufs aktive Ziel, ohne aktives Ziel in den Puffer.
    const opts = ['<option value="">Automatisch</option>'];
    goals.forEach(g => {
        const sel = (selectedId != null && Number(selectedId) === g.id) ? ' selected' : '';
        const label = g.is_general ? `${g.name} (Puffer)` : (g.is_active ? `${g.name} (aktiv)` : g.name);
        opts.push(`<option value="${g.id}"${sel}>${esc(label)}</option>`);
    });
    return opts.join('');
}

async function saveAchEdit(id,d){
    const b={title:document.getElementById('ef_title_'+id).value.trim(),reward_amount:parseFloat(document.getElementById('ef_reward_'+id).value),unit:document.getElementById('ef_unit_'+id).value.trim(),start_value:parseFloat(document.getElementById('ef_start_'+id).value),threshold_increment:parseFloat(document.getElementById('ef_incr_'+id).value),direction:document.getElementById('ef_dir_'+id).value};
    const stepEl=document.getElementById('ef_step_'+id);
    if(stepEl && stepEl.value!==''){
        const sv=parseFloat(stepEl.value);
        if(!isNaN(sv) && sv>0) b.step_amount=sv;
    }
    const tv=document.getElementById('ef_target_'+id).value;b.target_value=tv===''?null:parseFloat(tv);
    const rgEl=document.getElementById('ef_rgid_'+id);
    if(rgEl){ b.reward_goal_id = rgEl.value === '' ? null : parseInt(rgEl.value,10); }
    // v2.9.0: Quelle und Parameter gehen immer zusammen mit. "Keine" loest die
    // Bindung; der Server raeumt die Parameter dann selbst weg.
    const qEl=document.getElementById('ef_auto_'+id);
    if(qEl){ b.auto_source = qEl.value || null; b.auto_params = qEl.value ? autoParamsLesen(id) : {}; }
    try{
        await apiCall('/api/achievements/'+id+'/edit',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
        if(d) d.close();
        haptic('success');showToast('Gespeichert');
        await Promise.all([loadAchievements(),loadSparziel(),loadSavingsGoals()]);
    }catch(e){haptic('error');showToast(e.message||'Speichern fehlgeschlagen',true);}
}

// Was ein neuer Wert an Meilensteinen bringt, steht in der Antwort
// (credited_milestones) -- daraus wird der Betrag, der in den Tank fliegt.
function neueGutschrift(a, antwort){
    const vorher=Number(a.credited_milestones||0), nachher=Number(antwort && antwort.credited_milestones);
    if(!isFinite(nachher) || nachher<=vorher) return 0;
    return (nachher-vorher)*Number(a.reward_amount||0);
}

async function milestonePlus(id){
    const a=achData.find(x=>x.id==id);if(!a)return;
    const step=Number(a.step_amount||a.threshold_increment||1);
    const nv=Number(a.current_value||0)+(a.direction==='decrease'?-step:step);
    const card=document.getElementById('achCard_'+id);
    if(card){card.classList.remove('ist-getippt');void card.offsetWidth;card.classList.add('ist-getippt');}
    haptic('tap');
    try{
        const r=await apiCall('/api/achievements/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_value:nv})});
        const betrag=neueGutschrift(a,r);
        if(betrag>0){haptic('success');belohnungFliegt(card,betrag);showToast('Meilenstein! +'+fmtEur(betrag));}
        else showToast('+'+fmtNum(step)+' '+(a.unit||''));
        await Promise.all([loadAchievements(),loadSparziel()]);
    }catch(e){haptic('error');showToast('Das hat nicht geklappt',true);}
}
async function updateAchievement(id,d){
    const el=document.getElementById('achInput_'+id);
    const v=el?el.value:'';if(v===''||v==null)return;
    const a=achData.find(x=>x.id==id);
    try{
        const r=await apiCall('/api/achievements/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_value:Number(v)})});
        if(d) d.close();
        haptic('success');
        const betrag=a?neueGutschrift(a,r):0;
        if(betrag>0) belohnungFliegt(document.getElementById('achCard_'+id),betrag);
        showToast(betrag>0?'Wert gesetzt · +'+fmtEur(betrag):'Wert gesetzt');
        await Promise.all([loadAchievements(),loadSparziel()]);
    }
    catch(e){haptic('error');showToast('Setzen fehlgeschlagen',true);}
}

// Nachtragen mit Datum
function openMilestoneModal(id){
    const a=achData.find(x=>x.id==id);
    if(!a)return;
    const nm=nextMilestone(a);
    const einheit=esc(a.unit||'');
    const step=fmtNum(a.step_amount||a.threshold_increment);
    const d=dialog('Nachtragen: '+a.title,`<form data-form>
        <p class="sz-dlg-hinweis">Jetzt ${fmtNum(a.current_value)} ${einheit}, nächster Meilenstein bei ${fmtNum(nm)} ${einheit}.</p>
        <label for="msDate">Datum</label>
        <input type="date" id="msDate" value="${todayIso()}" max="${todayIso()}">
        <label for="msValue">Wert danach</label>
        <input type="number" step="0.01" inputmode="decimal" id="msValue" placeholder="leer = +${step} ${einheit}">
        <label for="msNote">Notiz</label>
        <input type="text" id="msNote" placeholder="z. B. nach dem Sport gewogen">
        <div class="modal-fuss"><button type="submit" class="v-btn v-btn--primary">Nachtragen</button></div>
    </form>`);
    formular(d,()=>submitMilestone(id,d));
}
async function submitMilestone(id,d){
    const a=achData.find(x=>x.id==id);
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
    try{
        await apiCall('/api/achievements/'+id,{
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({current_value:nv, achieved_at:dateStr, note:noteVal||null})
        });
        if(d) d.close();
        haptic('success');
        showToast('Nachgetragen');
        await Promise.all([loadAchievements(),loadSparziel()]);
    }catch(e){
        haptic('error');
        showToast(e.message||'Nachtragen fehlgeschlagen',true);
    }
}

const PRESETS={
    meilenstein:{achReward:'3',achUnit:'x',achStart:'0',achIncr:'1',achStep:'1',achTarget:'',achDir:'increase'},
    wert:{achReward:'5',achUnit:'',achStart:'0',achIncr:'',achStep:'',achTarget:'',achDir:'increase'},
    abnehmend:{achReward:'7',achUnit:'kg',achStart:'',achIncr:'5',achStep:'1',achTarget:'',achDir:'decrease'}
};
/* v2.36.0: derselbe Dialog legt ein Achievement an ODER speichert es als
   Idee (``opts.idee``: {id, title, config}). Eine Idee traegt damit alle
   Werte und wird spaeter mit einem Tipp aktiviert. */
function dlgNeuesAchievement(opts){
    const o=opts||{}, idee=o.idee||null, c=(idee&&idee.config)||{};
    const titel=idee?(idee.id?'Idee ausarbeiten: Achievement':'Neue Idee: Achievement'):'Neues Achievement';
    const d=dialog(titel,`<form data-form>
        ${idee?'':`<p class="fp-label" style="margin-bottom:0.5rem">Vorlage</p>
        <div class="sz-reihe" id="achVorlagen">
            <button type="button" class="v-chip" data-preset="meilenstein">Zählen (+1)</button>
            <button type="button" class="v-chip" data-preset="wert">Wert messen</button>
            <button type="button" class="v-chip" data-preset="abnehmend">Abnehmend</button>
        </div>`}
        <label for="achTitle">Titel</label><input id="achTitle" placeholder="z. B. Bücher gelesen" value="${feldWert(idee&&idee.title)}">
        <div class="sz-felder">
            <div><label for="achReward">€ je Meilenstein</label><input id="achReward" type="number" step="0.01" inputmode="decimal" placeholder="5" value="${feldWert(c.reward_amount)}"></div>
            <div><label for="achUnit">Einheit</label><input id="achUnit" placeholder="km, kg, Buch" value="${feldWert(c.unit)}"></div>
            <div><label for="achStart">Startwert</label><input id="achStart" type="number" step="0.01" inputmode="decimal" placeholder="0" value="${feldWert(c.start_value)}"></div>
            <div><label for="achIncr">Meilenstein alle</label><input id="achIncr" type="number" step="0.01" inputmode="decimal" placeholder="5" value="${feldWert(c.threshold_increment)}"></div>
            <div><label for="achStep">Schritt je Tipp</label><input id="achStep" type="number" step="0.01" inputmode="decimal" placeholder="wie Meilenstein" value="${feldWert(c.step_amount)}"></div>
            <div><label for="achTarget">Zielwert</label><input id="achTarget" type="number" step="0.01" inputmode="decimal" placeholder="offen" value="${feldWert(c.target_value)}"></div>
            <div><label for="achDir">Richtung</label><select id="achDir"><option value="increase">Steigend</option><option value="decrease"${c.direction==='decrease'?' selected':''}>Fallend</option></select></div>
            <div><label for="achRewardGoal">Belohnung geht an</label><select id="achRewardGoal">${rewardGoalOptionsHTML(c.reward_goal_id||null)}</select></div>
        </div>
        <div class="modal-fuss">
            ${idee?`<button type="submit" class="v-btn v-btn--primary">${ikon('idee',16)} Als Idee speichern</button>`
                  :`<button type="button" class="v-btn" data-als-idee>${ikon('idee',16)} Als Idee</button>
                    <button type="submit" class="v-btn v-btn--primary">Anlegen</button>`}
        </div>
    </form>`,{breit:true});
    formular(d,()=>idee?ideeSpeichern(d,'milestone',idee.id,achievementAusForm()):createAchievement(d));
    beiKlick(d,'[data-als-idee]',()=>ideeSpeichern(d,'milestone',null,achievementAusForm()));
    d.root.querySelectorAll('[data-preset]').forEach(b=>b.addEventListener('click',()=>{
        d.root.querySelectorAll('[data-preset]').forEach(x=>x.classList.toggle('is-active',x===b));
        const p=PRESETS[b.dataset.preset];if(!p)return;
        Object.keys(p).forEach(id=>{const el=document.getElementById(id);if(el)el.value=p[id];});
    }));
    fokusAmRechner('achTitle');
}
/* Die Werte aus dem Formular -- oder null, wenn etwas fehlt (die Meldung
   steht dann schon da). Anlegen und Als-Idee-Speichern lesen dieselben. */
function achievementAusForm(){
    const t=document.getElementById('achTitle').value.trim(),r=parseFloat(document.getElementById('achReward').value),u=document.getElementById('achUnit').value.trim(),s=parseFloat(document.getElementById('achStart').value)||0,inc=parseFloat(document.getElementById('achIncr').value);
    const stepRaw=document.getElementById('achStep').value;
    const stepVal=stepRaw===''?null:parseFloat(stepRaw);
    const tv=document.getElementById('achTarget').value,tg=tv===''?null:parseFloat(tv),dir=document.getElementById('achDir').value;
    if(!t||isNaN(r)||!u||isNaN(inc)||inc<=0){showToast('Titel, Belohnung, Einheit und Meilenstein-Abstand ausfüllen',true);haptic('error');return null;}
    if(stepVal!==null && (isNaN(stepVal)||stepVal<=0)){showToast('Der Schritt je Tipp muss über 0 liegen (oder leer bleiben)',true);haptic('error');return null;}
    const body={title:t,reward_amount:r,unit:u,start_value:s,threshold_increment:inc,target_value:tg,direction:dir};
    if(stepVal!==null) body.step_amount=stepVal;
    const rgEl=document.getElementById('achRewardGoal');
    if(rgEl && rgEl.value){ body.reward_goal_id = parseInt(rgEl.value,10); }
    return body;
}
async function createAchievement(d){
    const body=achievementAusForm(); if(!body) return;
    try{
        await apiCall('/api/achievements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        if(d) d.close();
        haptic('success');
        showToast('Achievement angelegt');await loadAchievements();
    }catch(e){haptic('error');showToast(e.message||'Anlegen fehlgeschlagen',true);}
}
async function resetAchievement(id){
    if(!await askConfirm({title:'Achievement zurücksetzen?',
        text:'Alle Meilensteine und die daraus gesparten Beiträge werden entfernt.',
        ok:'Zurücksetzen',danger:true}))return false;
    try{const r=await apiCall('/api/achievements/'+id+'/reset',{method:'POST'});const s=r&&r.removed_count?` (${r.removed_count} Einträge, ${fmtEur(r.removed_sum||0)} entfernt)`:'';haptic('success');showToast('Zurückgesetzt'+s);await Promise.all([loadAchievements(),loadSparziel()]);return true;}
    catch(e){haptic('error');showToast('Zurücksetzen fehlgeschlagen',true);return false;}
}
function deleteAchievement(id){
    const a=achData.find(x=>x.id==id);
    const card=document.getElementById('achCard_'+id);
    if(card)card.classList.add('pending-delete');
    haptic('tap');
    showUndoToast(`„${a?.title||''}“ wird gelöscht`,
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

// ---- Wochenziele --------------------------------------------------------------
async function loadProgressGoals(){
    try{pgData=await apiCall('/api/progress-goals')||[];loadErrors.pg=false;renderProgressGoals();}
    catch(e){loadErrors.pg=true;renderProgressGoals();console.error(e);}
}

const WOCHENTAGE=['Mo','Di','Mi','Do','Fr','Sa','So'];
/* Der Wochenstreifen: sieben Tage, gefüllt, wo eingecheckt wurde; zwei
   Check-ins an einem Tag tragen die Zahl. Kommt aus ``current_dates`` --
   der Server liefert die Tage der laufenden Woche schon mit. */
function wochenStreifen(daten){
    const w=currentWeekInfo(), heute=todayIso();
    const zahl={};
    (daten||[]).forEach(d=>{const k=String(d).slice(0,10);zahl[k]=(zahl[k]||0)+1;});
    return '<span class="sz-streifen" aria-hidden="true">'+WOCHENTAGE.map((n,i)=>{
        const tag=new Date(w.start.getFullYear(),w.start.getMonth(),w.start.getDate()+i);
        const iso=isoTag(tag), k=zahl[iso]||0;
        let cls='sz-tag';
        if(k) cls+=' ist-voll';
        if(iso===heute) cls+=' ist-heute'; else if(iso>heute) cls+=' ist-spaeter';
        return `<span class="${cls}" data-tag="${iso}" data-n="${k}"><span class="sz-tag-n">${n}</span><span class="sz-tag-punkt">${k>1?k:''}</span></span>`;
    }).join('')+'</span>';
}
// Monatsziele haben keinen Wochenstreifen: dort zählt, wie viele, nicht wann.
function monatsPunkte(c,t,schwelle){
    const n=Math.min(Math.max(t,c),31);
    return '<span class="sz-punkte" aria-hidden="true">'+Array.from({length:n},(_,i)=>
        `<span class="sz-punkt${i<c?' ist-voll':''}${schwelle&&i===schwelle-1?' ist-schwelle':''}"></span>`).join('')+'</span>';
}

function wochenzielHTML(g){
    const c=Number(g.current_count||0),t=Math.max(1,Number(g.target_count||1)),fertig=c>=t;
    const monat=g.rhythm_type==='monthly';
    // v2.16.0: Teilbelohnung -- ab teilN Check-ins gibt es zum Periodenende
    // teilP % der Belohnung, falls das Ziel selbst nicht erreicht wird.
    const teilN=Number(g.partial_count||0),teilP=Number(g.partial_percent||0);
    const teilAn=teilN>0&&teilP>0&&teilN<t&&Number(g.reward_amount||0)>0;
    const teilBetrag=Number(g.reward_amount||0)*teilP/100;
    const streak=Number(g.streak||0);
    const bonusAmt=Number(g.streak_bonus_amount||0),bonusN=Number(g.streak_bonus_threshold||0);
    const einheit=n=>monat?(n===1?'Monat':'Monate'):(n===1?'Woche':'Wochen');
    const meta=[`<span class="sz-betrag">+${fmtEur(g.reward_amount)}</span>`];
    if(streak>0) meta.push(`<span class="sz-serie">${ikon('flamme',13)}${streak} ${einheit(streak)}</span>`);
    if(bonusAmt>0&&bonusN>0) meta.push(`<span title="Serienbonus ${fmtEur(bonusAmt)} nach ${bonusN} ${einheit(bonusN)} in Folge">Bonus ${streak%bonusN}/${bonusN}</span>`);
    if(teilAn&&!fertig) meta.push(c>=teilN
        ? `<span class="sz-gw-teil ist-sicher">+${fmtEur(teilBetrag)} sicher</span>`
        : `<span class="sz-gw-teil">ab ${teilN}: +${fmtEur(teilBetrag)}</span>`);
    const titel=esc(g.title);
    const wann=monat?'diesen Monat':'diese Woche';
    return `<div class="sz-gw${fertig?' ist-fertig':''}" id="pgCard_${g.id}">
        <span class="drag-handle" title="Ziehen zum Sortieren" aria-hidden="true">${ikon('griff',16)}</span>
        <button type="button" class="sz-gw-knopf" data-id="${g.id}" onclick="checkinProgress(${g.id})"
                aria-label="${titel}: einchecken. ${c} von ${t} ${wann}.">
            <span class="v-ring v-ring--gut sz-gw-ring" id="pgRing_${g.id}" aria-hidden="true">
                <svg viewBox="0 0 100 100"><circle class="v-ring-track" cx="50" cy="50" r="42"/><circle class="v-ring-fill" cx="50" cy="50" r="42"/><circle class="v-ring-over" cx="50" cy="50" r="42"/></svg>
                <span class="v-ring-txt"><strong class="sz-gw-zahl">${c}<small>/${t}</small></strong></span>
            </span>
            <span class="sz-gw-text">
                <span class="sz-gw-titel">${titel}</span>
                <span class="sz-gw-meta">${meta.join('<span class="sep">·</span>')}</span>
                ${monat?monatsPunkte(c,t,teilAn?teilN:0):wochenStreifen(g.current_dates)}
            </span>
            <span class="sz-gw-plus" aria-hidden="true">${ikon(fertig?'haken':'plus',20)}</span>
        </button>
        <button type="button" class="v-btn v-btn--ghost v-btn--icon sz-gw-mehr" onclick="dlgWochenziel(${g.id})" aria-label="Mehr zu „${titel}“">${ikon('mehr',18)}</button>
    </div>`;
}

function renderProgressGoals(){
    const l=document.getElementById('pgList');
    if(loadErrors.pg){l.innerHTML=fehlerHTML('Die Wochenziele konnten nicht geladen werden.','loadProgressGoals()');return;}
    if(!pgData.length){
        l.innerHTML=leerHTML('Noch kein Wochenziel. Eines zahlt, sobald du etwas oft genug geschafft hast: dreimal Sport, fünfmal lesen.','Wochenziel anlegen','dlgNeuesWochenziel()','haken');
        return;
    }
    // Wer mit der Tastatur eingecheckt hat, bleibt auf seiner Kachel stehen.
    const fokus=document.activeElement && document.activeElement.closest && document.activeElement.closest('.sz-gw-knopf');
    const fokusId=fokus ? fokus.dataset.id : null;
    l.innerHTML=pgData.map(wochenzielHTML).join('');
    pgData.forEach(g=>{
        const c=Number(g.current_count||0),t=Math.max(1,Number(g.target_count||1));
        const ring=document.getElementById('pgRing_'+g.id);
        const vorher=pgStand[g.id];
        // Der Ring läuft vom alten Stand zum neuen -- sonst stünde er nach
        // dem Neuzeichnen einfach da, und der Tipp hätte keine sichtbare Folge.
        if(ring && vorher && vorher.c!==c){VexRing.set(ring,{wert:vorher.c,ziel:t});void ring.getBoundingClientRect();}
        if(ring) VexRing.set(ring,{wert:c,ziel:t});
        const tage={};
        document.querySelectorAll('#pgCard_'+g.id+' .sz-tag').forEach(el=>{
            const n=Number(el.dataset.n||0);tage[el.dataset.tag]=n;
            if(vorher && n>(vorher.tage[el.dataset.tag]||0)) el.classList.add('ist-neu');
        });
        pgStand[g.id]={c:c,tage:tage};
    });
    if(fokusId){const k=l.querySelector('.sz-gw-knopf[data-id="'+fokusId+'"]');if(k)k.focus({preventScroll:true});}
}

async function checkinProgress(id){
    const g=pgData.find(x=>x.id==id); if(!g) return;
    const kachel=document.getElementById('pgCard_'+id);
    if(kachel){kachel.classList.remove('ist-getippt');void kachel.offsetWidth;kachel.classList.add('ist-getippt');}
    haptic('tap');
    try{
        const r=await apiCall('/api/progress-goals/'+id+'/checkin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
        let betrag=0;
        if(r&&r.paid_out) betrag+=Number(g.reward_amount||0);
        if(r&&r.streak_bonus_paid) betrag+=Number(g.streak_bonus_amount||0);
        let text='Eingecheckt';
        if(r&&r.streak_bonus_paid) text='Serienbonus! +'+fmtEur(betrag);
        else if(r&&r.paid_out) text='Geschafft! +'+fmtEur(betrag);
        if(betrag>0){haptic('success');belohnungFliegt(kachel,betrag);}
        toastMitAktion(text,'Rückgängig',()=>checkoutProgress(id));
        await Promise.all([loadProgressGoals(),loadSparziel()]);
    }catch(e){haptic('error');showToast('Check-in fehlgeschlagen',true);}
}
async function checkoutProgress(id){
    try{await apiCall('/api/progress-goals/'+id+'/checkout',{method:'DELETE'});haptic('tap');showToast('Zurückgenommen');await Promise.all([loadProgressGoals(),loadSparziel()]);}
    catch(e){haptic('error');showToast(e.message||'Zurücknehmen fehlgeschlagen',true);}
}

function dlgWochenziel(id){
    const g=pgData.find(x=>x.id==id); if(!g) return;
    const c=Number(g.current_count||0),t=Math.max(1,Number(g.target_count||1));
    const monat=g.rhythm_type==='monthly';
    const bonusN=Number(g.streak_bonus_threshold||0),bonusAmt=Number(g.streak_bonus_amount||0);
    const teilN=Number(g.partial_count||0),teilP=Number(g.partial_percent||0);
    const wert=(v)=>v==null||v===0?'':esc(v);
    const d=dialog(g.title,`<form data-form>
        <div class="sz-dlg-stand">
            <div><strong>${c} / ${t}</strong><span>${monat?'diesen Monat':'diese Woche'}</span></div>
            <button type="button" class="v-btn v-btn--sm" data-zurueck${c?'':' disabled'}>${ikon('zurueck',15)} Letzten zurücknehmen</button>
        </div>
        <h4 class="sz-dlg-h">Einstellungen</h4>
        <label for="pge_title_${id}">Titel</label><input id="pge_title_${id}" value="${esc(g.title||'')}">
        <div class="sz-felder">
            <div><label for="pge_reward_${id}">Belohnung (€)</label><input id="pge_reward_${id}" type="number" step="0.01" inputmode="decimal" value="${g.reward_amount!=null?esc(g.reward_amount):''}"></div>
            <div><label for="pge_target_${id}">Ziel-Anzahl</label><input id="pge_target_${id}" type="number" min="1" inputmode="numeric" value="${g.target_count||''}"></div>
            <div><label for="pge_rhythm_${id}">Rhythmus</label><select id="pge_rhythm_${id}"><option value="weekly" ${!monat?'selected':''}>Wöchentlich</option><option value="monthly" ${monat?'selected':''}>Monatlich</option></select></div>
            <div><label for="pge_rgid_${id}">Belohnung geht an</label><select id="pge_rgid_${id}">${rewardGoalOptionsHTML(g.reward_goal_id)}</select></div>
            <div><label for="pge_streakN_${id}">Serienbonus nach (0 = aus)</label><input id="pge_streakN_${id}" type="number" min="0" inputmode="numeric" value="${wert(bonusN)}"></div>
            <div><label for="pge_streakAmt_${id}">Serienbonus (€)</label><input id="pge_streakAmt_${id}" type="number" step="0.01" inputmode="decimal" value="${wert(bonusAmt)}"></div>
            <div><label for="pge_teilN_${id}">Teilbelohnung ab (0 = aus)</label><input id="pge_teilN_${id}" type="number" min="0" inputmode="numeric" value="${wert(teilN)}" placeholder="z. B. ${Math.max(1,t-2)}"></div>
            <div><label for="pge_teilP_${id}">Davon ausgezahlt (%)</label><input id="pge_teilP_${id}" type="number" min="0" max="100" step="1" inputmode="numeric" value="${wert(teilP)}" placeholder="50"></div>
        </div>
        <h4 class="sz-dlg-h">Vergangene ${monat?'Monate':'Wochen'}</h4>
        <div id="pgHist_${id}"><span class="skel skel-line long"></span><span class="skel skel-line short"></span></div>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell',16)} Löschen</button>
            <button type="submit" class="v-btn v-btn--primary">Speichern</button>
        </div>
    </form>`,{breit:true});
    formular(d,()=>savePgEdit(id,d));
    beiKlick(d,'[data-zurueck]',()=>{d.close();checkoutProgress(id);});
    beiKlick(d,'[data-weg]',()=>{d.close();deleteProgress(id);});
    loadPgHistory(id);
}

// pro Wochenziel: aktuell geladene Limit-Anzahl merken (Standard 12)
const pgHistLimit = {};
async function loadPgHistory(id, limit){
    if(limit==null) limit=pgHistLimit[id]||12;
    pgHistLimit[id]=limit;
    const box=document.getElementById('pgHist_'+id);
    try{
        const rows=await apiCall('/api/progress-goals/'+id+'/history?limit='+limit)||[];
        if(!box||!box.isConnected)return;
        const g=pgData.find(x=>x.id==id);
        const isMonthly=g&&g.rhythm_type==='monthly';
        if(!rows.length){box.innerHTML='<p class="sz-dlg-hinweis">Noch keine abgeschlossene Periode.</p>';return;}
        const rowsHtml=rows.map(r=>{
            let label;
            if(isMonthly){
                label=new Date(r.start).toLocaleDateString('de-DE',{month:'long',year:'numeric'});
            } else {
                const w=String(r.period_key||'').split('-W')[1];
                label=`KW ${parseInt(w,10)} · ${fmtSpanne(new Date(r.start+'T12:00:00'),new Date(r.end+'T12:00:00'))}`;
            }
            const zustand=r.fulfilled?'ok':(r.is_current?'jetzt':(r.current_count>0?'teil':''));
            const zeichen=r.fulfilled?ikon('haken',14):(r.is_current?ikon('uhr',14):(r.current_count>0?ikon('haken',14):'–'));
            const sub=[];
            if(r.log_dates&&r.log_dates.length) sub.push(r.log_dates.length+(r.log_dates.length===1?' Check-in':' Check-ins'));
            if(r.is_current) sub.push('läuft');
            if(r.paid_out) sub.push('Belohnung ausgezahlt');
            else if(r.partial_paid!=null) sub.push('Teilbelohnung +'+fmtEur(r.partial_paid));
            return `<div class="sz-hist-zeile${r.is_current?' ist-jetzt':''}">
                <span class="sz-hist-mark${zustand?' ist-'+zustand:''}">${zeichen}</span>
                <span class="sz-hist-main"><span class="sz-hist-lbl">${esc(label)}</span>${sub.length?`<span class="sz-hist-sub">${esc(sub.join(' · '))}</span>`:''}</span>
                <span class="sz-hist-zahl${r.fulfilled?' ist-ok':''}">${r.current_count}/${r.target_count}</span>
                ${r.is_current?'':`<button type="button" class="v-btn v-btn--sm" onclick="backdateToPeriod(${id},'${esc(r.start)}')" aria-label="Check-in nachtragen: ${esc(label)}">+1</button>`}
            </div>`;
        }).join('');
        const canMore=rows.length>=limit&&limit<52;
        box.innerHTML=`<div class="sz-hist">${rowsHtml}</div>`
            +(canMore?`<button type="button" class="v-btn v-btn--ghost v-btn--sm sz-hist-mehr" onclick="loadPgHistory(${id},${Math.min(limit+12,52)})">Ältere laden</button>`:'');
    }catch(e){if(box)box.innerHTML='<p class="sz-dlg-hinweis">Der Verlauf konnte nicht geladen werden.</p>';}
}
async function backdateToPeriod(id,startDate){
    try{
        await apiCall('/api/progress-goals/'+id+'/checkin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({log_date:startDate})});
        haptic('success');
        showToast('Nachgetragen');
        await Promise.all([loadProgressGoals(),loadSparziel(),loadPgHistory(id)]);
    }catch(e){haptic('error');showToast(e.message||'Nachtragen fehlgeschlagen',true);}
}
async function savePgEdit(id,d){
    const b={
        title:document.getElementById('pge_title_'+id).value.trim(),
        reward_amount:parseFloat(document.getElementById('pge_reward_'+id).value),
        target_count:parseInt(document.getElementById('pge_target_'+id).value,10),
        rhythm_type:document.getElementById('pge_rhythm_'+id).value,
        streak_bonus_threshold:parseInt(document.getElementById('pge_streakN_'+id).value,10)||0,
        streak_bonus_amount:parseFloat(document.getElementById('pge_streakAmt_'+id).value)||0,
        partial_count:parseInt(document.getElementById('pge_teilN_'+id).value,10)||0,
        partial_percent:parseFloat(document.getElementById('pge_teilP_'+id).value)||0
    };
    const rgEl=document.getElementById('pge_rgid_'+id);
    if(rgEl){ b.reward_goal_id = rgEl.value === '' ? null : parseInt(rgEl.value,10); }
    try{
        await apiCall('/api/progress-goals/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
        if(d) d.close();
        haptic('success');showToast('Gespeichert');
        await Promise.all([loadProgressGoals(),loadSavingsGoals()]);
    }
    catch(e){haptic('error');showToast(e.message||'Speichern fehlgeschlagen',true);}
}

/* v2.36.0: wie beim Achievement -- derselbe Dialog legt an oder speichert
   eine fertige Idee (``opts.idee``). */
function dlgNeuesWochenziel(opts){
    const o=opts||{}, idee=o.idee||null, c=(idee&&idee.config)||{};
    const titel=idee?(idee.id?'Idee ausarbeiten: Wochenziel':'Neue Idee: Wochenziel'):'Neues Wochenziel';
    const d=dialog(titel,`<form data-form>
        <label for="pgTitle">Titel</label><input id="pgTitle" placeholder="z. B. Dreimal Sport" value="${feldWert(idee&&idee.title)}">
        <div class="sz-felder">
            <div><label for="pgReward">Belohnung (€)</label><input id="pgReward" type="number" step="0.01" inputmode="decimal" placeholder="5" value="${feldWert(c.reward_amount)}"></div>
            <div><label for="pgTarget">Ziel-Anzahl</label><input id="pgTarget" type="number" min="1" inputmode="numeric" placeholder="3" value="${feldWert(c.target_count)}"></div>
            <div><label for="pgRhythm">Rhythmus</label><select id="pgRhythm"><option value="weekly">Wöchentlich</option><option value="monthly"${c.rhythm_type==='monthly'?' selected':''}>Monatlich</option></select></div>
            <div><label for="pgRewardGoal">Belohnung geht an</label><select id="pgRewardGoal">${rewardGoalOptionsHTML(c.reward_goal_id||null)}</select></div>
        </div>
        <h4 class="sz-dlg-h">Extras</h4>
        <div class="sz-felder">
            <div><label for="pgStreakN">Serienbonus nach (0 = aus)</label><input id="pgStreakN" type="number" min="0" inputmode="numeric" placeholder="4" value="${c.streak_bonus_threshold?feldWert(c.streak_bonus_threshold):''}"></div>
            <div><label for="pgStreakAmt">Serienbonus (€)</label><input id="pgStreakAmt" type="number" step="0.01" inputmode="decimal" placeholder="10" value="${c.streak_bonus_amount?feldWert(c.streak_bonus_amount):''}"></div>
            <div><label for="pgTeilN">Teilbelohnung ab (0 = aus)</label><input id="pgTeilN" type="number" min="0" inputmode="numeric" placeholder="2" value="${c.partial_count?feldWert(c.partial_count):''}"></div>
            <div><label for="pgTeilP">Davon ausgezahlt (%)</label><input id="pgTeilP" type="number" min="0" max="100" step="1" inputmode="numeric" placeholder="50" value="${c.partial_percent?feldWert(c.partial_percent):''}"></div>
        </div>
        <div class="modal-fuss">
            ${idee?`<button type="submit" class="v-btn v-btn--primary">${ikon('idee',16)} Als Idee speichern</button>`
                  :`<button type="button" class="v-btn" data-als-idee>${ikon('idee',16)} Als Idee</button>
                    <button type="submit" class="v-btn v-btn--primary">Anlegen</button>`}
        </div>
    </form>`);
    formular(d,()=>idee?ideeSpeichern(d,'progress',idee.id,wochenzielAusForm()):createProgressGoal(d));
    beiKlick(d,'[data-als-idee]',()=>ideeSpeichern(d,'progress',null,wochenzielAusForm()));
    fokusAmRechner('pgTitle');
}
function wochenzielAusForm(){
    const t=document.getElementById('pgTitle').value.trim();
    const r=parseFloat(document.getElementById('pgReward').value);
    const rt=document.getElementById('pgRhythm').value;
    const tg=parseInt(document.getElementById('pgTarget').value,10);
    const sn=parseInt(document.getElementById('pgStreakN').value,10)||0;
    const sa=parseFloat(document.getElementById('pgStreakAmt').value)||0;
    const tn=parseInt(document.getElementById('pgTeilN').value,10)||0;
    const tp=parseFloat(document.getElementById('pgTeilP').value)||0;
    if(!t||isNaN(r)||!tg){showToast('Titel, Belohnung und Ziel-Anzahl ausfüllen',true);haptic('error');return null;}
    const body={title:t,reward_amount:r,rhythm_type:rt,target_count:tg,streak_bonus_amount:sa,streak_bonus_threshold:sn,partial_count:tn,partial_percent:tp};
    const rgEl=document.getElementById('pgRewardGoal');
    if(rgEl && rgEl.value){ body.reward_goal_id = parseInt(rgEl.value,10); }
    return body;
}
async function createProgressGoal(d){
    const body=wochenzielAusForm(); if(!body) return;
    try{
        await apiCall('/api/progress-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        if(d) d.close();
        haptic('success');
        showToast('Wochenziel angelegt');await loadProgressGoals();
    }catch(e){haptic('error');showToast(e.message||'Anlegen fehlgeschlagen',true);}
}
function deleteProgress(id){
    const g=pgData.find(x=>x.id==id);
    const card=document.getElementById('pgCard_'+id);
    if(card)card.classList.add('pending-delete');
    haptic('tap');
    showUndoToast(`„${g?.title||''}“ wird gelöscht`,
        ()=>{if(card)card.classList.remove('pending-delete');},
        async()=>{
            try{const r=await apiCall('/api/progress-goals/'+id,{method:'DELETE'});
                const s=r&&r.removed_count?` (${r.removed_count} Einträge, ${fmtEur(r.removed_sum||0)})`:'';
                haptic('success');
                showToast('Gelöscht'+s);
                delete pgStand[id];
                await Promise.all([loadProgressGoals(),loadSparziel()]);
            }catch(e){haptic('error');showToast('Löschen fehlgeschlagen',true);await loadProgressGoals();}
        }
    );
}

// ---- Sparziele, Puffer, Wunschliste, Ideen ---------------------------------
async function loadSavingsGoals(){
    try{
        const list=await apiCall('/api/savings-goals')||[];
        savingsGoalsCache = list;
        const general = list.find(g => g.is_general) || null;
        const goals   = list.filter(g => !g.is_general);
        renderIdeenSummary(goals, general);
        renderBufferCard(general, goals);
        const box=document.getElementById('sgList');
        if(!box)return;
        if(!goals.length){
            box.innerHTML=leerHTML('Noch kein Sparziel. Ohne Ziel sammelt der Puffer jede Belohnung ein; was dort liegt, lässt sich später übertragen.','Sparziel anlegen','startNewGoal()','ziel');
            return;
        }
        box.innerHTML = goals.map(renderSavingsGoalCard).join('');
    }catch(e){
        console.error(e);
        const box=document.getElementById('sgList');
        if(box) box.innerHTML=fehlerHTML('Die Sparziele konnten nicht geladen werden.','loadSavingsGoals()');
    }
}

// Kopfzeile des Reiters: alles zusammen, davon auf Zielen, davon im Puffer
function renderIdeenSummary(goals, general){
    const box=document.getElementById('ideenSummary');
    if(!box)return;
    const onGoals = goals.reduce((a,g)=>a+Number(g.saved_amount||0),0);
    const buf     = Number((general && general.saved_amount) || 0);
    // Welches Ziel aktiv ist, sagt die Karte darunter; oben steht, was
    // zusammen daliegt.
    box.innerHTML =
        `<div><span>Gespart</span><strong class="ist-plus">${fmtEur(onGoals+buf)}</strong></div>`
        +`<div><span>Auf Zielen</span><strong>${fmtEur(onGoals)}</strong></div>`
        +`<div><span>Im Puffer</span><strong>${fmtEur(buf)}</strong></div>`;
}

function renderBufferCard(general, goals){
    const box=document.getElementById('bufferBox');
    if(!box)return;
    if(!general){box.innerHTML='';return;}
    const saved=Number(general.saved_amount||0);
    const canTransfer = saved>0.005 && goals.length>0;
    const hasActive = goals.some(g=>g.is_active);
    const hint = hasActive
        ? 'Hier landet, was das aktive Ziel übersteigen würde, und jede Belohnung, die dem Puffer fest zugewiesen ist.'
        : 'Gerade ist kein Ziel aktiv: jede Belohnung läuft hierher.';
    box.innerHTML=`<div class="sz-puffer">
        <span class="sz-puffer-ikon">${ikon('muenze',22)}</span>
        <div class="sz-puffer-text">
            <span class="sz-puffer-lbl">${esc(general.name)} · Puffer</span>
            <strong>${fmtEur(saved)}</strong>
            <span class="sz-puffer-hint">${hint}</span>
        </div>
        <button type="button" class="v-btn" onclick="openTransferModal()" ${canTransfer?'':'disabled'}>${ikon('tauschen',16)} Übertragen</button>
    </div>`;
}

function renderSavingsGoalCard(g){
    const saved=Number(g.saved_amount||0);
    const target=Number(g.target_amount||0);
    const p=pct(saved,target);
    const active=!!g.is_active;
    const full=target>0 && saved>=target-0.005;
    const missing=Math.max(0,target-saved);
    const pill = full   ? '<span class="sz-pille ist-voll">Erreicht</span>'
               : active ? '<span class="sz-pille ist-aktiv">Aktiv</span>'
               :          '<span class="sz-pille">Ruht</span>';
    const actions=[];
    if(active){
        if(full) actions.push(`<button type="button" class="v-btn v-btn--primary" onclick="openCompleteModal()">${ikon('pokal',16)} Abschließen</button>`);
        actions.push(`<button type="button" class="v-btn" onclick="pauseSavingsGoal(${g.id})">Pausieren</button>`);
    }else{
        actions.push(`<button type="button" class="v-btn" onclick="activateSavingsGoal(${g.id})">Aktivieren</button>`);
    }
    if(g.link) actions.push(`<a class="v-btn v-btn--ghost v-btn--icon" href="${esc(g.link)}" target="_blank" rel="noopener noreferrer" aria-label="„${esc(g.name)}“ ansehen (${esc(linkKurz(g.link))})" title="${esc(linkKurz(g.link))}">${ikon('extern',17)}</a>`);
    actions.push(`<button type="button" class="v-btn v-btn--ghost v-btn--icon" onclick="dlgZiel(${g.id})" aria-label="Mehr zu „${esc(g.name)}“">${ikon('mehr',18)}</button>`);
    return `<div class="sz-ziel${active?' ist-aktiv':''}" id="sgCard_${g.id}">
        <div class="sz-ziel-kopf"><span class="sz-ziel-name">${esc(g.name)}</span>${pill}</div>
        <div class="sz-ziel-betrag">${fmtEur(saved)} <small>von ${fmtEur(target)}</small></div>
        <div class="sz-balken"><i style="width:${p.toFixed(1)}%"></i></div>
        <div class="sz-ziel-meta"><span>${fmtNum(p,0)} %</span><span>${full?'geschafft':'noch '+fmtEur(missing)}</span></div>
        <div class="sz-ziel-aktionen">${actions.join('')}</div>
    </div>`;
}

function dlgZiel(id){
    const g=(savingsGoalsCache||[]).find(x=>x.id===id); if(!g) return;
    const d=dialog(g.name,`<form data-form>
        <label for="zlName">Name</label><input id="zlName" value="${esc(g.name||'')}">
        <label for="zlTarget">Zielbetrag (€)</label><input id="zlTarget" type="number" step="0.01" inputmode="decimal" value="${g.target_amount!=null?esc(g.target_amount):''}">
        <label for="zlLink">Link <span class="sz-freiwillig">wo es das gibt</span></label><input id="zlLink" type="url" inputmode="url" autocomplete="off" placeholder="https://…" value="${feldWert(g.link)}">
        ${aufgebenZeile(id)}
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell',16)} Löschen</button>
            <button type="submit" class="v-btn v-btn--primary">Speichern</button>
        </div>
    </form>`);
    formular(d,async()=>{
        const n=document.getElementById('zlName').value.trim();
        const t=parseFloat(document.getElementById('zlTarget').value);
        if(!n||isNaN(t)||t<=0){showToast('Name und Zielbetrag ausfüllen',true);haptic('error');return;}
        try{
            await apiCall('/api/savings-goal/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,target_amount:t,link:document.getElementById('zlLink').value.trim()})});
            d.close();haptic('success');showToast('Gespeichert');
            await Promise.all([loadSavingsGoals(),loadSparziel()]);
        }catch(e){haptic('error');showToast(e.message||'Speichern fehlgeschlagen',true);}
    });
    beiKlick(d,'[data-weg]',async()=>{if(await deleteSavingsGoal(id)) d.close();});
    beiKlick(d,'[data-aufgeben]',()=>{d.close();dlgAufgeben(id);});
}

/* v2.35.0 -- Sparziel aufgeben. Fuer „ich will das Ding nicht mehr“:
   Loeschen naehme das Angesparte mit, Abschliessen machte eine Trophaee
   daraus. Hier bleibt das Geld gespart und zieht in den Puffer; von dort
   geht es per Uebertrag an ein neues Ziel. Einen freien Uebertrag zwischen
   Zielen gibt es bewusst nicht. */
function aufgebenZeile(id){
    const g=(savingsGoalsCache||[]).find(x=>x.id===id);
    if(!g) return '';
    const saved=Number(g.saved_amount||0);
    return `<div class="sz-aufgeben">
        <span class="sz-aufgeben-text"><strong>Keine Lust mehr darauf?</strong>
            <span>${saved>0.005?`Die ${fmtEur(saved)} kommen in den Puffer.`:'Auf dem Ziel liegt nichts.'}</span></span>
        <button type="button" class="v-btn" data-aufgeben>${ikon('archiv',16)} Aufgeben</button>
    </div>`;
}
function dlgAufgeben(id){
    const g=(savingsGoalsCache||[]).find(x=>x.id===id); if(!g) return;
    const saved=Number(g.saved_amount||0);
    const d=dialog(`„${g.name}“ aufgeben`,`<form data-form>
        <p class="sz-aufgeben-satz">${saved>0.005
            ?`Die <strong>${fmtEur(saved)}</strong> bleiben gespart und kommen in den Puffer. Von dort kannst du sie später einem neuen Ziel geben.`
            :'Auf dem Ziel liegt nichts.'} Das Ziel verschwindet, eine Trophäe gibt es nicht.</p>
        <label for="agGrund">Warum? <span class="sz-freiwillig">freiwillig</span></label>
        <textarea id="agGrund" rows="3" maxlength="500" placeholder="z. B. Doch lieber ein Gravelbike"></textarea>
        <div class="modal-fuss">
            <button type="submit" class="v-btn v-btn--primary">${ikon('archiv',16)} Aufgeben</button>
        </div>
    </form>`);
    formular(d,async()=>{
        const knopf=d.root.querySelector('[type=submit]');
        knopf.disabled=true;
        try{
            const r=await apiCall('/api/savings-goals/'+id+'/give-up',{method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({note:document.getElementById('agGrund').value.trim()||null})});
            d.close();haptic('success');
            showToast(r&&r.moved?`Aufgegeben – ${fmtEur(r.moved)} im Puffer`:'Aufgegeben');
            await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements(),loadProgressGoals(),loadLog()]);
        }catch(e){knopf.disabled=false;haptic('error');showToast(e.message||'Aufgeben fehlgeschlagen',true);}
    });
    fokusAmRechner('agGrund');
}

// Neues Sparziel, optional vorbefüllt (aus der Wunschliste)
function startNewGoal(name, price, link){
    const d=dialog('Neues Sparziel',`<form data-form>
        <label for="sgNewName">Name</label><input id="sgNewName" placeholder="z. B. Neues Fahrrad" value="${esc(name||'')}">
        <label for="sgNewTarget">Zielbetrag (€)</label><input id="sgNewTarget" type="number" step="0.01" inputmode="decimal" placeholder="500" value="${price!=null&&price!==''?esc(price):''}">
        <label for="sgNewLink">Link <span class="sz-freiwillig">wo es das gibt</span></label><input id="sgNewLink" type="url" inputmode="url" autocomplete="off" placeholder="https://…" value="${feldWert(link)}">
        <label class="sz-check"><input type="checkbox" id="sgNewActivate" checked> Gleich aktivieren (das bisherige Ziel ruht mit seinem Stand)</label>
        <div class="modal-fuss"><button type="submit" class="v-btn v-btn--primary">Anlegen</button></div>
    </form>`);
    formular(d,()=>createSavingsGoal(d));
    fokusAmRechner(name?'sgNewTarget':'sgNewName');
    haptic('tap');
}
async function createSavingsGoal(d){
    const name=document.getElementById('sgNewName').value.trim();
    const target=parseFloat(document.getElementById('sgNewTarget').value);
    const activate=document.getElementById('sgNewActivate').checked;
    const link=document.getElementById('sgNewLink').value.trim()||null;
    if(!name||isNaN(target)||target<=0){showToast('Name und Zielbetrag ausfüllen',true);haptic('error');return;}
    try{
        await apiCall('/api/savings-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,target_amount:target,activate,link})});
        if(d) d.close();
        haptic('success');showToast(activate?'Sparziel angelegt und aktiv':'Sparziel angelegt');
        await Promise.all([loadSavingsGoals(),loadSparziel()]);
    }catch(e){haptic('error');showToast(e.message||'Anlegen fehlgeschlagen',true);}
}
async function activateSavingsGoal(id){
    try{
        await apiCall('/api/savings-goals/'+id+'/activate',{method:'POST'});
        haptic('success');showToast('Aktiviert — das bisherige Ziel ruht mit seinem Stand');
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements(),loadProgressGoals()]);
    }catch(e){haptic('error');showToast(e.message||'Aktivieren fehlgeschlagen',true);}
}
// v1.43.0: Ziel pausieren, ohne ein anderes zu aktivieren -- danach laeuft
// jede Belohnung in den Puffer.
async function pauseSavingsGoal(id){
    try{
        await apiCall('/api/savings-goals/'+id+'/deactivate',{method:'POST'});
        haptic('success');showToast('Pausiert — Belohnungen laufen jetzt in den Puffer');
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements(),loadProgressGoals()]);
    }catch(e){haptic('error');showToast(e.message||'Pausieren fehlgeschlagen',true);}
}
async function deleteSavingsGoal(id){
    const g=(savingsGoalsCache||[]).find(x=>x.id===id);
    const name=g?g.name:'Sparziel';
    const saved=Number((g&&g.saved_amount)||0);
    if(!await askConfirm({title:`Sparziel „${name}“ löschen?`,
        text:saved>0.005?`Die ${fmtEur(saved)} auf diesem Ziel werden dabei entfernt.`:'Auf dem Ziel liegt nichts.',
        ok:'Löschen',danger:true}))return false;
    try{
        const r=await apiCall('/api/savings-goals/'+id,{method:'DELETE'});
        haptic('success');
        showToast('Gelöscht'+(r&&r.removed_sum?` (${fmtEur(r.removed_sum)} entfernt)`:''));
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements(),loadProgressGoals()]);
        return true;
    }catch(e){haptic('error');showToast(e.message||'Löschen fehlgeschlagen',true);return false;}
}

// v1.26.0: Übertrag vom Puffer aufs Sparziel
function openTransferModal(){
    const goals = (savingsGoalsCache||[]).filter(g => !g.is_general);
    const buffer = (savingsGoalsCache||[]).find(g => g.is_general);
    if(!goals.length){ showToast('Kein Sparziel vorhanden',true); return; }
    if(!buffer || Number(buffer.saved_amount||0) <= 0){ showToast('Der Puffer ist leer',true); return; }
    const bufAmt = Number(buffer.saved_amount||0);
    const active = goals.find(g => g.is_active);
    const optionen = goals.map(g => {
        const saved = Number(g.saved_amount||0), tgt = Number(g.target_amount||0);
        const remaining = tgt > 0 ? Math.max(0, tgt - saved) : null;
        const label = g.name + (g.is_active?' (aktiv)':'') + (remaining != null ? ` — noch ${fmtEur(remaining)}` : '');
        const dis = remaining != null && remaining <= 0.005 ? ' disabled' : '';
        const selAttr = (active && g.id === active.id) ? ' selected' : '';
        return `<option value="${g.id}"${selAttr}${dis}>${esc(label)}</option>`;
    }).join('');
    const d=dialog('Vom Puffer übertragen',`<form data-form>
        <p class="sz-dlg-hinweis">Im Puffer: ${fmtEur(bufAmt)}</p>
        <label for="tfGoal">Auf</label><select id="tfGoal">${optionen}</select>
        <label for="tfAmount">Betrag (€)</label>
        <input type="number" step="0.01" min="0.01" max="${bufAmt.toFixed(2)}" inputmode="decimal" id="tfAmount" placeholder="z. B. 25,00">
        <div class="sz-reihe" id="tfQuickBtns"></div>
        <label for="tfNote">Notiz</label><input type="text" id="tfNote" placeholder="optional">
        <div class="modal-fuss"><button type="submit" class="v-btn v-btn--primary">${ikon('tauschen',16)} Übertragen</button></div>
    </form>`);
    formular(d,()=>submitTransfer(d));
    renderTransferQuickButtons();
    document.getElementById('tfGoal').addEventListener('change',renderTransferQuickButtons);
    fokusAmRechner('tfAmount');
}
function renderTransferQuickButtons(){
    const buffer = (savingsGoalsCache||[]).find(g => g.is_general);
    const bufAmt = Number((buffer && buffer.saved_amount) || 0);
    const gid = parseInt(document.getElementById('tfGoal').value,10);
    const g = (savingsGoalsCache||[]).find(x => x.id === gid);
    const saved = Number((g && g.saved_amount) || 0), tgt = Number((g && g.target_amount) || 0);
    const remaining = tgt > 0 ? Math.max(0, tgt - saved) : null;
    const options = [
        { lbl: '25 %', val: bufAmt * 0.25 },
        { lbl: '50 %', val: bufAmt * 0.5 },
        { lbl: 'Alles', val: bufAmt },
    ];
    if (remaining != null && remaining > 0 && remaining < bufAmt) {
        options.push({ lbl: 'Rest zum Ziel', val: remaining });
    }
    const box=document.getElementById('tfQuickBtns');
    box.innerHTML = options.map(o =>
        `<button type="button" class="v-chip" data-betrag="${o.val.toFixed(2)}">${o.lbl} · ${fmtEur(o.val)}</button>`).join('');
    box.querySelectorAll('[data-betrag]').forEach(b=>b.addEventListener('click',()=>{
        document.getElementById('tfAmount').value=b.dataset.betrag;
        box.querySelectorAll('[data-betrag]').forEach(x=>x.classList.toggle('is-active',x===b));
    }));
}
async function submitTransfer(d){
    const gid = parseInt(document.getElementById('tfGoal').value,10);
    const amount = parseFloat(document.getElementById('tfAmount').value);
    const note = (document.getElementById('tfNote').value||'').trim();
    if(!gid){ showToast('Ziel wählen',true); haptic('error'); return; }
    if(!(amount > 0)){ showToast('Einen Betrag über 0 eingeben',true); haptic('error'); return; }
    try{
        const res = await apiCall('/api/savings-goals/'+gid+'/transfer-from-buffer',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ amount, note: note||null })
        });
        if(d) d.close();
        haptic('success');
        showToast(`${fmtEur(res.amount)} übertragen`);
        await Promise.all([loadSavingsGoals(),loadSparziel(),loadAchievements()]);
    }catch(e){
        haptic('error');
        showToast(e.message||'Übertrag fehlgeschlagen',true);
    }
}

async function loadPotentialGoals(){
    const box=document.getElementById('potList'); if(!box)return;
    try{
        const d=await apiCall('/api/potential-goals')||[];
        potentialCache=d;
        box.innerHTML = d.length ? '<div class="rec-list">'+d.map(p=>{
            const price=(p.estimated_price!=null&&p.estimated_price!=='')?Number(p.estimated_price):null;
            const meta=[price!=null?'':'Preis offen', p.link?linkKurz(p.link):''].filter(Boolean).join(' · ');
            return `<button type="button" class="rec-row" id="potLi_${p.id}" onclick="dlgWunsch(${p.id})">
                <span class="rec-mark" style="--tone:var(--sz-ton)">${ikon('einkauf',16)}</span>
                <span class="rec-main"><span class="rec-title">${esc(p.name)}</span>${meta?`<span class="rec-meta">${esc(meta)}</span>`:''}</span>
                ${price!=null?`<span class="rec-side"><span class="rec-val">${fmtEur(price)}</span></span>`:''}
                <span class="rec-go">${ikon('pfeil',16)}</span>
            </button>`;
        }).join('')+'</div>' : leerHTML('Noch kein Wunsch notiert. Ein Wunsch mit Preis wird mit einem Tipp zum Sparziel.','','','einkauf');
    }catch(e){
        console.error(e);
        box.innerHTML=fehlerHTML('Die Wunschliste konnte nicht geladen werden.','loadPotentialGoals()');
    }
}
/* v2.36.0: ein Wunsch laesst sich aendern (vorher nur ansehen und loeschen)
   -- sonst kaeme ein Link nie nachtraeglich hinein. */
function dlgWunsch(id){
    const w=(potentialCache||[]).find(x=>x.id===id); if(!w) return;
    const d=dialog(w.name,`<form data-form>
        <label for="wuName">Name</label><input id="wuName" value="${feldWert(w.name)}">
        <label for="wuPrice">Preis (€)</label><input id="wuPrice" type="number" step="0.01" inputmode="decimal" placeholder="offen" value="${feldWert(w.estimated_price)}">
        <label for="wuLink">Link <span class="sz-freiwillig">wo es das gibt</span></label><input id="wuLink" type="url" inputmode="url" autocomplete="off" placeholder="https://…" value="${feldWert(w.link)}">
        ${w.link?`<p class="sz-link-zeile">${linkKnopf(w.link,linkKurz(w.link)||'Ansehen')}</p>`:''}
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger v-btn--icon" data-weg aria-label="Wunsch löschen" title="Löschen">${ikon('muell',17)}</button>
            <button type="button" class="v-btn" data-ziel>${ikon('ziel',16)} Als Sparziel</button>
            <button type="submit" class="v-btn v-btn--primary">Speichern</button>
        </div>
    </form>`);
    formular(d,async()=>{
        const n=document.getElementById('wuName').value.trim();
        const pv=document.getElementById('wuPrice').value;
        if(!n){showToast('Name fehlt',true);haptic('error');return;}
        try{
            await apiCall('/api/potential-goals/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({name:n,estimated_price:pv===''?null:parseFloat(pv),link:document.getElementById('wuLink').value.trim()})});
            d.close();haptic('success');showToast('Gespeichert');await loadPotentialGoals();
        }catch(e){haptic('error');showToast(e.message||'Speichern fehlgeschlagen',true);}
    });
    beiKlick(d,'[data-ziel]',()=>{d.close();startWishGoal(id);});
    beiKlick(d,'[data-weg]',()=>{d.close();deletePotential(id);});
}
// Wunsch als Sparziel uebernehmen: fuellt nur das Formular vor, angelegt
// wird erst mit "Anlegen" -- so bleibt der Preis noch korrigierbar.
function startWishGoal(id){
    const w=(potentialCache||[]).find(x=>x.id===id);
    if(!w)return;
    startNewGoal(w.name, w.estimated_price!=null?Number(w.estimated_price):'', w.link||'');
}
function dlgNeuerWunsch(){
    const d=dialog('Neuer Wunsch',`<form data-form>
        <label for="potName">Name</label><input id="potName" placeholder="z. B. Fahrrad">
        <label for="potPrice">Preis (€)</label><input id="potPrice" type="number" step="0.01" inputmode="decimal" placeholder="optional">
        <label for="potLink">Link <span class="sz-freiwillig">wo es das gibt</span></label><input id="potLink" type="url" inputmode="url" autocomplete="off" placeholder="https://…">
        <div class="modal-fuss"><button type="submit" class="v-btn v-btn--primary">Hinzufügen</button></div>
    </form>`);
    formular(d,()=>createPotential(d));
    fokusAmRechner('potName');
}
async function createPotential(d){
    const n=document.getElementById('potName').value.trim(),pv=document.getElementById('potPrice').value,pr=pv===''?null:parseFloat(pv);
    if(!n){showToast('Name fehlt',true);haptic('error');return;}
    const lk=document.getElementById('potLink').value.trim()||null;
    try{await apiCall('/api/potential-goals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,estimated_price:pr,link:lk})});if(d)d.close();haptic('success');await loadPotentialGoals();}
    catch(e){haptic('error');showToast(e.message||'Hinzufügen fehlgeschlagen',true);}
}
function deletePotential(id){
    const li=document.getElementById('potLi_'+id);
    if(li)li.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Wunsch wird gelöscht',
        ()=>{if(li)li.classList.remove('pending-delete');},
        async()=>{try{await apiCall('/api/potential-goals/'+id,{method:'DELETE'});haptic('success');await loadPotentialGoals();}catch(e){haptic('error');await loadPotentialGoals();}}
    );
}
// Ideen kennen genau zwei Sorten -- alles andere bleibt ohne Marke. Aeltere
// Freitext-Kategorien werden dadurch nicht mehr als Marke ausgespielt.
const IDEA_KINDS = {
    milestone: { label: 'Achievement' },
    progress:  { label: 'Wochenziel' },
};
function ideaKind(cat){
    const k=(cat||'').trim().toLowerCase();
    if(k==='milestone'||k==='meilenstein') return 'milestone';
    if(k==='progress'||k==='wochenziel'||k==='weekly') return 'progress';
    return null;
}
// Was eine ausgearbeitete Idee verspricht, in einer Zeile.
function ideeZusammenfassung(i){
    const c=i.config; if(!c) return '';
    if(ideaKind(i.category)==='progress')
        return `${c.target_count}× ${c.rhythm_type==='monthly'?'pro Monat':'pro Woche'} · ${fmtEur(c.reward_amount)}`;
    return `${fmtEur(c.reward_amount)} alle ${fmtNum(c.threshold_increment)} ${c.unit||''}`.trim();
}
/* Eine Idee speichern -- neu (id null) oder ausgearbeitet. Die Vorlage ist
   genau das, was beim Anlegen ginge, ohne den Titel (der steht an der Idee). */
async function ideeSpeichern(d, art, id, body){
    if(!body) return;
    const config=Object.assign({},body); delete config.title;
    try{
        await apiCall(id?'/api/future-ideas/'+id:'/api/future-ideas',{method:id?'PUT':'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({title:body.title,category:art,config:config})});
        if(d) d.close();
        haptic('success');showToast(id?'Idee gespeichert':'Als Idee gespeichert – aktivieren unter „Ziele“');
        await loadFutureIdeas();
    }catch(e){haptic('error');showToast(e.message||'Speichern fehlgeschlagen',true);}
}
async function ideeAktivieren(id,d){
    try{
        const r=await apiCall('/api/future-ideas/'+id+'/activate',{method:'POST'});
        if(d) d.close();
        haptic('success');showToast(r&&r.art==='progress'?'Wochenziel aktiviert':'Achievement aktiviert');
        await Promise.all([loadFutureIdeas(),loadProgressGoals(),loadAchievements()]);
    }catch(e){haptic('error');showToast(e.message||'Aktivieren fehlgeschlagen',true);}
}

async function loadFutureIdeas(){
    const box=document.getElementById('ideaList'); if(!box)return;
    try{
        const d=await apiCall('/api/future-ideas')||[];
        ideaCache=d;
        box.innerHTML = d.length ? '<div class="rec-list">'+d.map(i=>{
            const kind=ideaKind(i.category);
            const bereit=!!(kind&&i.config);
            const meta=bereit?'bereit · '+ideeZusammenfassung(i):(kind?'noch nicht ausgearbeitet':'');
            return `<button type="button" class="rec-row" id="ideaLi_${i.id}" onclick="dlgIdee(${i.id})">
                <span class="rec-mark" style="--tone:${bereit?'var(--sz-ton)':'var(--warn)'}">${ikon('idee',16)}</span>
                <span class="rec-main"><span class="rec-title">${esc(i.title)}</span>${meta?`<span class="rec-meta">${esc(meta)}</span>`:''}</span>
                ${kind?`<span class="sz-art">${IDEA_KINDS[kind].label}</span>`:''}
                <span class="rec-go">${ikon('pfeil',16)}</span>
            </button>`;
        }).join('')+'</div>' : leerHTML('Noch keine Idee gesammelt: ein Wochenziel oder Achievement fertig vorbereiten und später mit einem Tipp aktivieren – oder einfach etwas ohne Preisschild notieren.','','','idee');
    }catch(e){
        console.error(e);
        box.innerHTML=fehlerHTML('Die Ideen konnten nicht geladen werden.','loadFutureIdeas()');
    }
}
function dlgIdee(id){
    const i=(ideaCache||[]).find(x=>x.id===id); if(!i) return;
    const kind=ideaKind(i.category);
    const bereit=!!(kind&&i.config);
    const d=dialog(i.title,`<dl class="sz-details"><dt>Art</dt><dd>${kind?IDEA_KINDS[kind].label:'offen'}</dd>
            ${bereit?`<dt>Vorlage</dt><dd>${esc(ideeZusammenfassung(i))}</dd>`:''}</dl>
        <p class="sz-dlg-hinweis">${bereit?'Fertig ausgearbeitet – „Aktivieren“ legt es genau so an.'
            :kind?'Noch nicht ausgearbeitet. Mit Belohnung und allem Übrigen lässt sie sich später mit einem Tipp aktivieren.'
            :'Eine Notiz ohne Art – etwas ohne Preisschild.'}</p>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger v-btn--icon" data-weg aria-label="Idee löschen" title="Löschen">${ikon('muell',17)}</button>
            ${kind?`<button type="button" class="v-btn${bereit?'':' v-btn--primary'}" data-ausarbeiten>${bereit?'Bearbeiten':'Ausarbeiten'}</button>`:''}
            ${bereit?`<button type="button" class="v-btn v-btn--primary" data-aktivieren>${ikon('haken',16)} Aktivieren</button>`:''}
            ${kind?'':'<button type="button" class="v-btn" data-zu>Schließen</button>'}
        </div>`);
    beiKlick(d,'[data-weg]',()=>{d.close();deleteIdea(id);});
    beiKlick(d,'[data-zu]',()=>d.close());
    beiKlick(d,'[data-ausarbeiten]',()=>{
        d.close();
        if(kind==='progress') dlgNeuesWochenziel({idee:i}); else dlgNeuesAchievement({idee:i});
    });
    beiKlick(d,'[data-aktivieren]',()=>ideeAktivieren(id,d));
}
function dlgNeueIdee(){
    const d=dialog('Neue Idee',`<form data-form>
        <label for="ideaTitle">Titel</label><input id="ideaTitle" placeholder="z. B. Sprachkurs">
        <label for="ideaKind">Wird vielleicht</label>
        <select id="ideaKind"><option value="">— offen —</option><option value="milestone">ein Achievement</option><option value="progress">ein Wochenziel</option></select>
        <p class="sz-dlg-hinweis">„Ausarbeiten“ legt Belohnung und alles Übrige gleich fest – dann ist die Idee später mit einem Tipp aktiv.</p>
        <div class="modal-fuss">
            <button type="submit" class="v-btn">Nur notieren</button>
            <button type="button" class="v-btn v-btn--primary" data-ausarbeiten>Ausarbeiten</button>
        </div>
    </form>`);
    formular(d,()=>createIdea(d));
    beiKlick(d,'[data-ausarbeiten]',()=>{
        const titel=document.getElementById('ideaTitle').value.trim();
        const art=document.getElementById('ideaKind').value;
        if(!art){showToast('Erst wählen, was es werden soll',true);haptic('error');return;}
        d.close();
        const idee={id:null,title:titel,config:null};
        if(art==='progress') dlgNeuesWochenziel({idee}); else dlgNeuesAchievement({idee});
    });
    fokusAmRechner('ideaTitle');
}
async function createIdea(d){
    const t=document.getElementById('ideaTitle').value.trim(),c=document.getElementById('ideaKind').value;
    if(!t){showToast('Titel fehlt',true);haptic('error');return;}
    try{await apiCall('/api/future-ideas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,category:c||null})});if(d)d.close();haptic('success');await loadFutureIdeas();}
    catch(e){haptic('error');showToast('Hinzufügen fehlgeschlagen',true);}
}
function deleteIdea(id){
    const li=document.getElementById('ideaLi_'+id);
    if(li)li.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Idee wird gelöscht',
        ()=>{if(li)li.classList.remove('pending-delete');},
        async()=>{try{await apiCall('/api/future-ideas/'+id,{method:'DELETE'});haptic('success');await loadFutureIdeas();}catch(e){haptic('error');await loadFutureIdeas();}}
    );
}

// ---- Chronik -------------------------------------------------------------------
/* v2.11.8: Die Zeile ueber dem Log nannte „N Eintraege, +X EUR“ und meinte
   damit die geladenen -- und geladen wurden 500. Die Auskunft ueber das Ganze
   kommt vom Server (`/api/activity-log/summary`); die Liste darunter bleibt
   gekuerzt, solange die Zeile nicht behauptet, sie sei alles. */
const LOG_GRENZE = 500;
let logSummen = null;          // {all:{count,amount}, by_type:{…}} oder null
let logGekappt = false;

async function loadLog(){
    try{
        logRaw=await apiCall('/api/activity-log?limit='+LOG_GRENZE)||[];
        logGekappt = logRaw.length >= LOG_GRENZE;
        loadErrors.log=false;
        renderLog();
    }
    catch(e){loadErrors.log=true;document.getElementById('logSum').textContent='';document.getElementById('logBody').innerHTML=fehlerHTML('Die Chronik konnte nicht geladen werden.','loadLog()');return;}
    // Getrennt geholt: bleibt die Auskunft aus, steht die Liste trotzdem da.
    try{ logSummen = await apiCall('/api/activity-log/summary'); renderLog(); }
    catch(e){ logSummen = null; renderLog(); }
}
function filterLogRows(){
    const q=document.getElementById('logSearch').value.trim().toLowerCase();
    let rows=logRaw;
    if(logFilter!=='all')rows=rows.filter(r=>(r.type||'')===logFilter);
    if(q)rows=rows.filter(r=>(r.title||'').toLowerCase().includes(q)||(r.description||'').toLowerCase().includes(q)||(r.note||'').toLowerCase().includes(q));
    return rows;
}
/* Welche Zahl in der Kopfzeile steht, haengt davon ab, ob wir sie wissen
   koennen. Ohne Textsuche deckt sich die Auswahl mit einer Art, die der Server
   ganz gezaehlt hat -- dann seine Zahl. Mit Textsuche wird im Browser gefiltert;
   das ist genau, solange nichts abgeschnitten wurde, und wird sonst benannt. */
function logKopfzahlen(rows){
    const suche=document.getElementById('logSearch').value.trim();
    if(!suche && logSummen){
        const q = logFilter==='all' ? logSummen.all
                                    : (logSummen.by_type||{})[logFilter];
        if(q) return {count:Number(q.count)||0, amount:Number(q.amount)||0, genau:true};
    }
    return {count:rows.length,
            amount:rows.reduce((a,r)=>a+Number(r.amount||0),0),
            genau:!logGekappt};
}
function renderLog(){
    const rows=filterLogRows();
    const sumBox=document.getElementById('logSum');
    const filtered=!!(document.getElementById('logSearch').value.trim()||logFilter!=='all');
    if(rows.length){
        const z=logKopfzahlen(rows);
        // Zwei verschiedene Einschraenkungen, und beide muessen dastehen:
        // die Zahl kann ueber weniger gerechnet sein als es gibt, und die
        // Liste darunter kann kuerzer sein als die Zahl.
        const hinweis = !z.genau ? ` · gezählt in den neuesten ${logRaw.length}`
            : (logGekappt ? ` · Liste zeigt die neuesten ${rows.length}` : '');
        sumBox.textContent=`${z.count} ${z.count===1?'Eintrag':'Einträge'}${filtered?' (gefiltert)':''} · +${fmtEur(z.amount)}${hinweis}`;
    } else sumBox.textContent='';
    const body=document.getElementById('logBody');
    if(!rows.length){
        body.innerHTML=`<div class="empty"><p class="empty-text">${filtered
            ?'Nichts gefunden. Ein anderer Suchbegriff oder eine andere Art im Filter hilft.'
            :'Noch nichts passiert. Der erste Check-in steht hier.'}</p></div>`;
        return;
    }
    if(logView==='weekly') renderLogWeekly(rows,body,filtered); else renderLogFlat(rows,body);
}
const LOG_LABELS={initial:'Start',milestone:'Meilenstein',checkin:'Check-in',streak_bonus:'Bonus',transfer:'Übertrag',progress:'Fortschritt',aufgegeben:'Aufgegeben',aenderung:'Änderung'};
const LOG_ZEICHEN={initial:['muenze','var(--text-2)'],milestone:['ziel','var(--sz-ton)'],checkin:['haken','var(--sz-ton)'],
    streak_bonus:['flamme','var(--warn)'],transfer:['tauschen','var(--info)'],progress:['pfeil','var(--text-3)'],
    aufgegeben:['archiv','var(--text-2)'],aenderung:['stift','var(--text-3)']};
function logRowHtml(r){
    const t=r.type||'initial';
    const z=LOG_ZEICHEN[t]||['uhr','var(--text-3)'];
    const amt=Number(r.amount||0), delta=Number(r.delta||0);
    let wert, cls;
    // Fortschritts-Zeilen zahlen nichts aus -- statt eines leeren Strichs steht
    // dort die Wertaenderung selbst (z.B. "+2,5 km").
    if(amt>0){wert='+'+fmtEur(amt);cls=t==='streak_bonus'?'ist-bonus':'ist-plus';}
    else if(amt<0){wert=fmtEur(amt);cls='ist-delta';}
    else if(t==='progress'&&delta){wert=(delta>0?'+':'−')+fmtNum(Math.abs(delta))+(r.unit?' '+esc(r.unit):'');cls='ist-delta';}
    else{wert='—';cls='ist-null';}
    const meta=[`<span>${LOG_LABELS[t]||esc(t)}</span>`];
    if(r.description) meta.push(`<span>${esc(r.description)}</span>`);
    if(r.note) meta.push(`<span class="sz-log-notiz">„${esc(r.note)}“</span>`);
    return `<button type="button" class="rec-row" id="logRow_${t}_${r.log_id}" onclick="dlgLogEintrag('${t}',${r.log_id})">
        <span class="rec-mark" style="--tone:${z[1]}">${ikon(z[0],15)}</span>
        <span class="rec-main"><span class="rec-title">${esc(r.title||'')}</span><span class="rec-meta">${meta.join('<span class="sep">·</span>')}</span></span>
        <span class="rec-side"><span class="rec-val ${cls}">${wert}</span></span>
    </button>`;
}
function tagesBloecke(rows){
    const byDay={};
    rows.forEach(r=>{const d=r.date?String(r.date).slice(0,10):'unbekannt';(byDay[d]=byDay[d]||[]).push(r);});
    return Object.keys(byDay).sort().reverse().map(day=>{
        const daySum=byDay[day].reduce((a,r)=>a+Number(r.amount||0),0);
        return `<div class="sz-tag-kopf"><span>${esc(fmtDay(day))}</span><span>${daySum>0?'+'+fmtEur(daySum):''}</span></div>
            <div class="rec-list sz-log">${byDay[day].map(logRowHtml).join('')}</div>`;
    }).join('');
}
function renderLogFlat(rows,body){
    body.innerHTML=tagesBloecke(rows);
}
function renderLogWeekly(rows,body,alleOffen){
    const byWeek={};
    rows.forEach(r=>{
        const d=new Date(r.date);
        const {week,year}=isoWeek(d);
        const key=`${year}-W${String(week).padStart(2,'0')}`;
        if(!byWeek[key]){
            const monday=new Date(d.getFullYear(),d.getMonth(),d.getDate()-((d.getDay()||7)-1));
            const sunday=new Date(monday.getFullYear(),monday.getMonth(),monday.getDate()+6);
            byWeek[key]={rows:[],week,year,start:monday,end:sunday};
        }
        byWeek[key].rows.push(r);
    });
    const keys=Object.keys(byWeek).sort().reverse();
    // Offen steht die neueste Woche -- auch wenn in der laufenden noch nichts
    // passiert ist. Beim Suchen stehen alle offen, sonst versteckt der Filter
    // seine eigenen Treffer.
    const offenKey=keys[0];
    body.innerHTML=keys.map(key=>{
        const w=byWeek[key];
        const total=w.rows.reduce((a,r)=>a+Number(r.amount||0),0);
        const offen=alleOffen||key===offenKey;
        return `<section class="sz-woche-gruppe">
            <button type="button" class="sz-woche-kopf" aria-expanded="${offen}" aria-controls="logWeek_${key}" onclick="toggleWeek('${key}')">
                <span class="sz-woche-lbl">KW ${w.week} · ${fmtSpanne(w.start,w.end)}</span>
                <span class="sz-woche-n">${w.rows.length} ${w.rows.length===1?'Eintrag':'Einträge'}</span>
                <span class="sz-woche-summe">${total>0?'+'+fmtEur(total):''}</span>
                <span class="sz-woche-pfeil">${ikon('pfeil',16)}</span>
            </button>
            <div class="sz-woche-inhalt" id="logWeek_${key}"${offen?'':' hidden'}>${tagesBloecke(w.rows)}</div>
        </section>`;
    }).join('');
}
function toggleWeek(key){
    const inhalt=document.getElementById('logWeek_'+key);
    if(!inhalt) return;
    inhalt.hidden=!inhalt.hidden;
    const kopf=document.querySelector('[aria-controls="logWeek_'+key+'"]');
    if(kopf) kopf.setAttribute('aria-expanded', String(!inhalt.hidden));
}

/* Der Filter nennt im Ruhezustand seinen Stand, die Auswahl schwebt darunter
   (DESIGN 6b). Eine Art und eine Sicht gelten sofort; das Feld bleibt offen,
   bis man daneben tippt, weil man oft beides umstellt. */
function filterEinrichten(){
    const knopf=document.getElementById('logFilterBtn'), pop=document.getElementById('logFilterPop');
    const zu=()=>{pop.hidden=true;knopf.setAttribute('aria-expanded','false');};
    knopf.addEventListener('click',e=>{
        e.stopPropagation();
        const auf=pop.hidden;
        pop.hidden=!auf;knopf.setAttribute('aria-expanded',String(auf));
    });
    document.addEventListener('click',e=>{if(!pop.hidden&&!pop.contains(e.target)&&!knopf.contains(e.target))zu();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!pop.hidden){zu();knopf.focus();}});
    pop.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>{
        logFilter=c.dataset.filter;
        pop.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('is-active',x===c));
        filterStand();renderLog();
    }));
    pop.querySelectorAll('[data-view]').forEach(c=>c.addEventListener('click',()=>{
        logView=c.dataset.view;
        pop.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('is-active',x===c));
        filterStand();renderLog();
    }));
}
function filterStand(){
    const art=document.querySelector('#logFilterArten [data-filter="'+logFilter+'"]');
    const text=(art?art.textContent:'Alle')+(logView==='all'?' · nach Tag':'');
    document.getElementById('logFilterLbl').textContent=text;
    document.getElementById('logFilterBtn').classList.toggle('has-active',logFilter!=='all'||logView!=='weekly');
}

function dlgLogEintrag(type, logId){
    const row = logRaw.find(x => (x.type||'initial')===type && x.log_id===logId);
    if(!row){showToast('Eintrag nicht gefunden',true);return;}
    const amt=Number(row.amount||0);
    const d=dialog(row.title||LOG_LABELS[type]||'Eintrag',`<form data-form>
        <dl class="sz-details">
            <dt>Art</dt><dd>${esc(LOG_LABELS[type]||type)}</dd>
            <dt>Wann</dt><dd>${esc(fmtDate(row.date))}</dd>
            ${row.description?`<dt>Was</dt><dd>${esc(row.description)}</dd>`:''}
            ${amt?`<dt>Betrag</dt><dd>${amt>0?'+':''}${fmtEur(amt)}</dd>`:''}
        </dl>
        ${type==='aenderung'?`<div class="modal-fuss"><button type="button" class="v-btn" data-zu>Schließen</button></div>`
        :`<label for="noteText">Notiz</label>
        <textarea id="noteText" rows="3" placeholder="Freie Notiz …">${esc(row.note||'')}</textarea>
        <div class="modal-fuss">
            ${row.deletable?`<button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell',16)} Löschen</button>`:''}
            <button type="submit" class="v-btn v-btn--primary">Notiz speichern</button>
        </div>`}
    </form>`);
    // Eine Aenderung ist ein Protokolleintrag, keine Notizstelle.
    beiKlick(d,'[data-zu]',()=>d.close());
    if(type==='aenderung'){ const f=d.root.querySelector('[data-form]'); if(f) f.addEventListener('submit',e=>e.preventDefault()); return; }
    formular(d,()=>submitNote(type,logId,d));
    beiKlick(d,'[data-weg]',()=>{d.close();deleteLogEntry(type,logId);});
}
async function submitNote(type, logId, d){
    const note = document.getElementById('noteText').value.trim();
    let url;
    if(type==='checkin')            url = '/api/progress-logs/'+logId+'/note';
    else if(type==='milestone')     url = '/api/achievement-logs/'+logId+'/note';
    else if(type==='progress')      url = '/api/achievement-progress-logs/'+logId+'/note';
    else                            url = '/api/savings-transactions/'+logId+'/note'; // initial, streak_bonus
    try{
        await apiCall(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({note})});
        const row = logRaw.find(x => (x.type||'initial')===type && x.log_id===logId);
        if(row) row.note = note;
        if(d) d.close();
        haptic('success');
        showToast(note ? 'Notiz gespeichert' : 'Notiz entfernt');
        renderLog();
    }catch(e){
        haptic('error');
        showToast(e.message || 'Speichern fehlgeschlagen', true);
    }
}
function deleteLogEntry(type,id){
    const row=document.getElementById(`logRow_${type}_${id}`);
    if(row)row.classList.add('pending-delete');
    haptic('tap');
    showUndoToast('Eintrag wird gelöscht',
        ()=>{if(row)row.classList.remove('pending-delete');},
        async()=>{
            try{
                if(type==='checkin'){
                    const r=await apiCall('/api/progress-logs/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast(r&&r.payout_removed?'Gelöscht, samt Sparbeitrag':'Gelöscht');
                    await Promise.all([loadLog(),loadProgressGoals(),loadSparziel()]);
                } else if(type==='milestone'){
                    const r=await apiCall('/api/achievement-logs/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast(r&&r.payout_removed?'Gelöscht, samt Sparbeitrag':'Gelöscht');
                    await Promise.all([loadLog(),loadAchievements(),loadSparziel()]);
                } else if(type==='progress'){
                    // Nimmt die Wertaenderung am Ziel gleich mit zurueck
                    await apiCall('/api/achievement-progress-logs/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast('Zurückgenommen');
                    await Promise.all([loadLog(),loadAchievements()]);
                } else if(type==='initial'||type==='streak_bonus'||type==='transfer'){
                    const r=await apiCall('/api/savings-transactions/'+id,{method:'DELETE'});
                    haptic('success');
                    showToast(r && r.pair_deleted ? 'Übertrag zurückgebucht' : 'Gelöscht');
                    await Promise.all([loadLog(),loadSparziel(),loadSavingsGoals()]);
                }
            }catch(e){haptic('error');showToast(e.message||'Löschen fehlgeschlagen',true);await loadLog();}
        }
    );
}
async function downloadBackup(){
    try{
        const data=await apiCall('/api/backup');
        const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
        const url=URL.createObjectURL(blob);
        const a=document.createElement('a');
        const date=todayIso();
        a.href=url;a.download=`vexbob-backup-${date}.json`;
        document.body.appendChild(a);a.click();a.remove();
        URL.revokeObjectURL(url);
        haptic('success');
        showToast('Sicherung heruntergeladen');
    }catch(e){haptic('error');showToast('Sicherung fehlgeschlagen',true);}
}

// ---- Trophäen -------------------------------------------------------------------
const TROPHAEEN_FARBEN=['gold','silver','bronze','blue','green','purple'];
async function loadTrophies(){
    try{
        trophyData=await apiCall('/api/trophies')||[];
        loadErrors.trophies=false;
        renderTrophies();
    }catch(e){
        loadErrors.trophies=true;
        const grid=document.getElementById('trophyGrid');
        grid.classList.add('ist-leer');
        grid.innerHTML=fehlerHTML('Die Trophäen konnten nicht geladen werden.','loadTrophies()');
    }
}
function renderTrophies(){
    const stats=document.getElementById('trophyStats');
    const grid=document.getElementById('trophyGrid');
    grid.classList.toggle('ist-leer',!trophyData.length);
    if(!trophyData.length){
        stats.textContent='';
        grid.innerHTML=leerHTML('Noch keine Trophäe. Die erste gibt es, wenn ein Sparziel voll ist und du es abschließt.','','','pokal');
        return;
    }
    const total=trophyData.reduce((a,t)=>a+Number(t.final_amount||0),0);
    const withDur=trophyData.filter(t=>t.duration_days);
    const avgDays=withDur.length?Math.round(withDur.reduce((a,t)=>a+t.duration_days,0)/withDur.length):null;
    const gekauft=trophyData.filter(t=>t.gekauft_am).length;
    stats.textContent=`${trophyData.length} · ${gekauft} gekauft · ${fmtEur(total)} gespart${avgDays!=null?' · Ø '+avgDays+' Tage':''}`;
    // v2.43.0: der Haken „gekauft“ sitzt in der Ecke der Kachel -- ein Tipp
    // darauf setzt ihn, die Kachel selbst oeffnet weiter den Dialog.
    grid.innerHTML=trophyData.map(t=>{
        const farbe=TROPHAEEN_FARBEN.indexOf(t.color)>=0?t.color:'gold';
        const date=t.completed_at?new Date(t.completed_at).toLocaleDateString('de-DE',{month:'short',year:'numeric'}):'';
        const an=!!t.gekauft_am;
        const hakenText=an?'Gekauft – Haken entfernen':'Als gekauft markieren';
        return `<div class="sz-trophae ${farbe}${an?' ist-gekauft':''}">
            <button type="button" class="sz-trophae-haupt" onclick="dlgTrophae(${t.id})">
                <span class="sz-trophae-icon" aria-hidden="true">${esc(t.icon||'🏆')}</span>
                <span class="sz-trophae-name">${esc(t.name)}</span>
                <span class="sz-trophae-betrag">${fmtEur(t.final_amount)}</span>
                <span class="sz-trophae-meta">${an?'gekauft am '+esc(new Date(t.gekauft_am+'T12:00:00').toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric'})):esc(date)+(t.duration_days?' · '+t.duration_days+' Tage':'')}</span>
            </button>
            <button type="button" class="sz-trophae-haken" aria-pressed="${an}" aria-label="${hakenText}" title="${hakenText}"
                onclick="trophaeGekauft(${t.id},${!an})">${ikon('haken',13)}</button>
        </div>`;
    }).join('');
}
/* Haken „gekauft“ setzen oder wegnehmen. Der Tag kommt aus dem Browser --
   abends um elf ist in UTC schon morgen. */
async function trophaeGekauft(id,gekauft){
    const heute=new Date();
    const tag=heute.getFullYear()+'-'+String(heute.getMonth()+1).padStart(2,'0')+'-'+String(heute.getDate()).padStart(2,'0');
    try{
        await apiCall('/api/trophies/'+id+'/gekauft',{method:'PUT',body:{gekauft,datum:tag}});
        haptic('success');
        showToast(gekauft?'Als gekauft markiert':'Haken entfernt');
        await loadTrophies();
        return true;
    }catch(e){haptic('error');showToast('Das ging nicht: '+(e.message||e),true);return false;}
}
function dlgTrophae(id){
    const t=trophyData.find(x=>x.id===id); if(!t) return;
    const date=t.completed_at?new Date(t.completed_at).toLocaleDateString('de-DE',{day:'numeric',month:'long',year:'numeric'}):'';
    const d=dialog(t.name,`<dl class="sz-details">
            <dt>Gespart</dt><dd>${fmtEur(t.final_amount)}${t.target_amount?' von '+fmtEur(t.target_amount):''}</dd>
            ${date?`<dt>Abgeschlossen</dt><dd>${esc(date)}</dd>`:''}
            ${t.duration_days?`<dt>Dauer</dt><dd>${t.duration_days} Tage</dd>`:''}
            ${t.note?`<dt>Notiz</dt><dd>„${esc(t.note)}“</dd>`:''}
        </dl>
        <button type="button" class="v-schalt-zeile sz-gekauft-zeile" role="switch" aria-checked="${!!t.gekauft_am}" data-gekauft>
            <span class="sz-gekauft-text"><strong>Gekauft</strong>
                <small>${t.gekauft_am?'am '+esc(new Date(t.gekauft_am+'T12:00:00').toLocaleDateString('de-DE',{day:'numeric',month:'long',year:'numeric'})):'noch nicht angeschafft'}</small></span>
            <span class="v-schalter" aria-hidden="true"></span>
        </button>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell',16)} Löschen</button>
            <button type="button" class="v-btn" data-zu>Schließen</button>
        </div>`);
    beiKlick(d,'[data-zu]',()=>d.close());
    beiKlick(d,'[data-weg]',async()=>{if(await deleteTrophy(id)) d.close();});
    beiKlick(d,'[data-gekauft]',async()=>{if(await trophaeGekauft(id,!t.gekauft_am)){d.close();dlgTrophae(id);}});
}
async function deleteTrophy(id){
    if(!await askConfirm({title:'Trophäe löschen?',
        text:'Sie verschwindet aus der Sammlung.',ok:'Löschen',danger:true}))return false;
    try{
        await apiCall('/api/trophies/'+id,{method:'DELETE'});
        haptic('success');
        showToast('Gelöscht');
        await loadTrophies();
        return true;
    }catch(e){haptic('error');showToast('Löschen fehlgeschlagen',true);return false;}
}

function openCompleteModal(){
    if(!glGoalId){showToast('Kein aktives Sparziel',true);haptic('error');return;}
    const d=dialog('Sparziel abschließen',`<form data-form>
        <p class="sz-dlg-hinweis">Das Ziel wird zur Trophäe unter „Verlauf“. Danach ist kein Ziel aktiv, und jede Belohnung läuft in den Puffer, bis du ein neues anlegst oder aktivierst.</p>
        <label for="cmName">Name der Trophäe</label>
        <input id="cmName" value="${esc(document.getElementById('goalName').textContent||'')}" placeholder="z. B. Rennrad gekauft">
        <div class="sz-felder">
            <div><label for="cmIcon">Zeichen</label>
                <select id="cmIcon">
                    <option value="🏆">🏆 Pokal</option><option value="🥇">🥇 Gold</option>
                    <option value="💎">💎 Diamant</option><option value="🎯">🎯 Ziel</option>
                    <option value="⭐">⭐ Stern</option><option value="🚀">🚀 Rakete</option>
                    <option value="🎉">🎉 Party</option><option value="💰">💰 Geld</option>
                </select></div>
            <div><label for="cmColor">Farbe</label>
                <select id="cmColor">
                    <option value="gold">Gold</option><option value="silver">Silber</option>
                    <option value="bronze">Bronze</option><option value="blue">Blau</option>
                    <option value="green">Grün</option><option value="purple">Lila</option>
                </select></div>
        </div>
        <label for="cmNote">Notiz</label><input id="cmNote" placeholder="z. B. Endlich!">
        <div class="modal-fuss"><button type="submit" class="v-btn v-btn--primary">${ikon('pokal',16)} Abschließen</button></div>
    </form>`);
    formular(d,()=>submitComplete(d));
    haptic('tap');
}
async function submitComplete(d){
    const name=document.getElementById('cmName').value.trim();
    if(!name){showToast('Der Trophäe fehlt ein Name',true);haptic('error');return;}
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
        if(d) d.close();
        haptic('success');
        showToast('Trophäe verdient!');
        // v1.43.0: Nach dem Abschluss ist das Ziel weg und kein neues aktiv →
        // State resetten, damit der Ring beim naechsten Ziel nicht von "voll"
        // runter-animiert und das Konfetti sauber neu triggern kann.
        prevGlTotal = null; prevGlPct = null; prevWasComplete = false;
        fireConfetti({count:260, duration:3200});
        setTimeout(()=>fireConfetti({count:140, duration:2400, originX: window.innerWidth*0.25, spread: Math.PI*0.9}), 300);
        setTimeout(()=>fireConfetti({count:140, duration:2400, originX: window.innerWidth*0.75, spread: Math.PI*0.9}), 600);
        await Promise.all([loadSparziel(),loadSavingsGoals(),loadAchievements(),loadProgressGoals()]);
        activateTab('verlauf');
        window.scrollTo({top:0,behavior:'smooth'});
    }catch(e){
        haptic('error');
        showToast(e.message||'Abschließen fehlgeschlagen',true);
    }
}

// ---- Reihenfolge ------------------------------------------------------------
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

document.getElementById('logoutBtn').addEventListener('click',()=>{clearToken();location.href='/private/login.html';});
document.querySelectorAll('.tabs .tab-btn').forEach(b=>b.addEventListener('click',()=>activateTab(b.dataset.tab)));
document.getElementById('logSearch').addEventListener('input',renderLog);
filterEinrichten();

(async function boot(){
    if(!isLoggedIn()){location.href='/private/login.html';return;}
    document.body.classList.add('ready');
    updatePeriodLabel();
    try{
        const me=await fetchMe(false);
        document.getElementById('userLabel').textContent=me.username;
    }catch(e){return;}
    activateTab((location.hash||'#heute').slice(1));
    try{await loadAll();}catch(e){showToast('Laden fehlgeschlagen',true);console.error(e);}
    // Sortable kommt mit ``defer``; ist es beim ersten Versuch noch nicht da,
    // klappt es nach dem Laden der Seite.
    initSortables();
    if(typeof Sortable==='undefined') window.addEventListener('load',initSortables,{once:true});
})();
