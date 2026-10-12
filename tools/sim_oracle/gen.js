// Genera escenarios aleatorios (con semilla) y guarda, para cada uno, las respuestas finales A y lo que calcula el simulador.
const ctx=require('./harness.js'); const S=ctx.window.__sim; const fs=require('fs');
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;}}
function safe(o){ return JSON.parse(JSON.stringify(o,(k,v)=>typeof v==='function'?undefined:v)); }
const SEEDS=+process.argv[2]||200;
const out=[];
for(let s=1;s<=SEEDS;s++){
  const rnd=mulberry(s*7919); const pick=a=>a[Math.floor(rnd()*a.length)]; const chance=p=>rnd()<p;
  S.newEval(); let g=0; let answers={}; const params={};
  for(;;){
    const n=S.current(); if(!n||n.kind==='fin'||g++>500) break;
    let val;
    if(n.kind==='choice'){
      const o=pick(n.opts); val=o.otro?(o.num?(1+Math.floor(rnd()*7)):'Algo distinto'):o.v;
      if(o.num&&n.id==='P15') val=pick([80,100,250,400,600,1200]);
    }
    else if(n.kind==='multi'){ const k=(n.opts||[]); val=k.filter(()=>chance(0.45)); if(!val.length&&n.min&&!n.none) val=[pick(k)]; if(n.id==='P11f'||/^P11g#/.test(n.id)||n.id==='P11e'){ if(!val.length) val=[pick(k)]; } }
    else if(n.kind==='ev'){
      const base=JSON.parse(JSON.stringify((n.def&&n.def.data)||{})); const e={data:base};
      if(chance(0.1)) e.skip=true;
      if(n.read==='speed'){ base.d1=pick([60,94,93.5,300,480,520,700]); base.d2=pick([60,94,300,500,540]); base.pd=pick([20,40,310,500]); base.pu=pick([20,35,320]); }
      if(n.read==='conn'){ base.ver=pick(['RED','USB','WIFI','NONE']); }
      if(n.read==='selftest'&&chance(0.4)) base.ip=pick(['192.168.0.50','192.168.1.77','10.0.0.5']);
      if(n.read==='selftest'&&chance(0.2)) delete base.ip;
      if(n.read==='scanner'){ base.cam=pick(['','DVR','NVR']); base.camIps=pick([0,3,5]); }
      if(n.read==='ipconfig'&&chance(0.3)) base.gw=pick(['192.168.0.1','10.0.0.1']);
      val=e;
    }
    else if(n.kind==='wifi'){ const w={}; n.zones.forEach(z=>{w[z]={dbm:pick([-50,-62,-70,-80]),ping:pick([20,60,150,250])};}); val=w; }
    else if(n.kind==='check'){ val={fails:[]}; }
    else if(n.kind==='text'){ val=n.id==='P03'?pick(['Av. Larco 345, Miraflores','Patio de comidas, El Refugio – Surco','Real Plaza Salaverry, patio de comidas','Jr. Callao 410, Lima']):n.def; }
    else if(n.kind==='links'){ val=chance(0.5)?[{d:'Recorrido del local',u:'https://drive.google.com/x'}]:[]; }
    else if(n.kind==='date'){ val=n.def; }
    else if(n.kind==='longtext'){ val=pick(['Recomiendo un supresor de picos.','Sin comentarios.','El cliente instalará tomas.']); }
    else if(n.kind==='rcard'){ val=Object.assign({},n.def,{libres:pick([0,1,2,3,'']),ocupados:pick([1,2,3])}); }
    else val=n.def;
    if(n.id==='P09'&&chance(0.6)){ val=pick(['REST_PESCADOS','REST_ORIENTAL','RESTAURANTE','CHIFA','PIZZERIA','PARRILLA','POLLERIA','FAST_FOOD','RESTOBAR','DISCOTECA_BAR','CAFETERIA','HELADERIA','HOSPEDAJE','RETAIL','OTRO']); }
    if(n.id==='P08'&&chance(0.5)) val=pick(['EN_OPERACION','EN_OBRA','POR_INAUGURAR','SISTEMA_ANTERIOR']);
    params[n.id]=val; S.autoAnswer(n,params);
  }
  const A=JSON.parse(JSON.stringify(S.A()));
  const {N,X,R,cur}=ctx.ctx(); const sc=ctx.scores(X,R);
  out.push(safe({seed:s,A,fin:!!cur&&cur.kind==='fin',stuck:cur&&cur.id,N:N.map(n=>({id:n.id,kind:n.kind,text:n.text,opts:n.opts,def:n.def,items:n.items,zones:n.zones,sel:n.sel,none:n.none})),X,R,scores:sc,pasos:ctx.genPasos(X,R),refs:ctx.refData(X,R),resumen:ctx.resumenIA(X,R),map:ctx.buildMap(X)}));
}
fs.writeFileSync('random.json',JSON.stringify(out));
console.log('escenarios',out.length,'completos',out.filter(o=>o.fin).length);
