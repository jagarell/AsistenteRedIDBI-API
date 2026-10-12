// Carga el JS del simulador en un contexto de Node con un DOM de mentira.
const fs=require('fs'), vm=require('vm');
// El simulador vive en docs/simulador/simulador.html del repo Android: pasa su ruta en SIM_HTML.
const html=fs.readFileSync(process.env.SIM_HTML,'utf8');
const src=/<script>([\s\S]*?)<\/script>/.exec(html)[1];
function stub(){
  const f=function(){};
  const p=new Proxy(f,{get:(t,k)=>{ if(k===Symbol.toPrimitive) return ()=>''; if(k==='length') return 0; if(k==='then') return undefined; return p;}, apply:()=>p, construct:()=>p, set:()=>true});
  return p;
}
const win={};
const ctx={document:stub(),navigator:stub(),localStorage:stub(),location:stub(),console,setTimeout:()=>0,clearTimeout:()=>0,setInterval:()=>0,requestAnimationFrame:()=>0,
  getComputedStyle:stub(),Date,Math,JSON,Array,Object,String,Number,RegExp,Set,Map,Promise,parseInt,parseFloat,isNaN,Symbol,Error,
  addEventListener:()=>{},window:win,matchMedia:stub(),visualViewport:stub(),ResizeObserver:function(){return {observe(){},disconnect(){}}},
  IntersectionObserver:function(){return {observe(){},disconnect(){}}},MutationObserver:function(){return {observe(){},disconnect(){}}},
  Image:function(){},FileReader:function(){},Blob:function(){},URL:{createObjectURL:()=>''},alert:()=>{},confirm:()=>true,prompt:()=>'' ,performance:{now:()=>0}};
ctx.window=Object.assign(win,{document:ctx.document,addEventListener:()=>{},innerWidth:400,innerHeight:800});
vm.createContext(ctx);
try{ vm.runInContext(src,ctx,{filename:'sim.js'}); }catch(e){ console.error('LOAD ERROR',e.message, (e.stack||'').split('\n').slice(0,4).join('\n')); }
module.exports=ctx;
if(require.main===module){ console.log(Object.keys(ctx.window.__sim||{})); console.log(typeof ctx.build, typeof ctx.evaluate, typeof ctx.scores); }
