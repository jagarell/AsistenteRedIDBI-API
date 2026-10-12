// Exporta un conjunto compacto de escenarios del simulador como "golden" para las pruebas de Python.
const ctx=require('./harness.js'); const S=ctx.window.__sim; const fs=require('fs');
const all=JSON.parse(fs.readFileSync('random.json','utf8'));
function safe(o){ return JSON.parse(JSON.stringify(o,(k,v)=>typeof v==='function'?undefined:v)); }
function compact(sc,name){
  const X=Object.assign({},sc.X); delete X.P;
  return {name,A:sc.A,N:sc.N.map(n=>({id:n.id,kind:n.kind,text:n.text,opts:n.opts,items:n.items,zones:n.zones})),X,
    it:sc.R.it.map(i=>({id:i.id,tipo:i.tipo,t:i.t,d:i.d,eq:i.eq,trabajo:i.trabajo})),con:sc.R.con,estado:sc.R.estado,V01:sc.R.V01,sp:sc.R.sp,
    scores:{g:sc.scores.g,att:sc.scores.att,areas:sc.scores.areas,cards:sc.scores.cards.map(c=>({k:c.k,v:c.v,why:c.why}))},
    pasos:sc.pasos,refs:{top:sc.refs.top.map(x=>({n:x.n,pct:x.pct})),recs:sc.refs.recs,sug:sc.refs.sug},resumen:sc.resumen,map:sc.map};
}
const out=[];
// casos del simulador
S.CASES.forEach((c,i)=>{ S.newEval(); let g=0; for(;;){const n=S.current(); if(!n||n.kind==='fin'||g++>500)break; S.autoAnswer(n,c.a);} 
  const A=JSON.parse(JSON.stringify(S.A())); const {N,X,R}=ctx.ctx(); const sc=ctx.scores(X,R);
  out.push(compact(safe({A,N:N.map(n=>({id:n.id,kind:n.kind,text:n.text,opts:n.opts,items:n.items,zones:n.zones})),X,R,scores:sc,pasos:ctx.genPasos(X,R),refs:ctx.refData(X,R),resumen:ctx.resumenIA(X,R),map:ctx.buildMap(X)}),'caso '+i+': '+c.t)); });
all.slice(0,35).forEach(sc=>out.push(compact(sc,'aleatorio '+sc.seed)));
fs.writeFileSync('sim_golden.json',JSON.stringify(out));
console.log(out.length, fs.statSync('sim_golden.json').size);
