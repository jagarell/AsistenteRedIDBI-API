const vm=require('vm'); const ctx=require('./harness.js');
const names=['RUBROS','PERFIL','PREP_ALL','MESA_ALL','CANALES','ZONAS_CANAL','ESTADOS','CONEX','MOZOS','MOZOS_RARO','BLOQUES','DIR_SUG','CHIP_PROV','CONN_TXT','REF_MIN','REF_RULE','REF_MAP','REF_SUGERIBLE','REF_FAM','REF_W','READ_FIELDS','VID_TIPOS','RC_FIELDS','ERR','EV_LIKE','EV_LIKE_N'];
const out={};
for(const n of names){ try{ out[n]=vm.runInContext(`(typeof ${n}==='undefined')?null:${n}`,ctx); }catch(e){ out[n]=null; console.error('skip',n,e.message);} }
require('fs').writeFileSync('catalog.json',JSON.stringify(out,null,1));
console.log(Object.entries(out).map(([k,v])=>k+':'+(v==null?'null':JSON.stringify(v).length)).join(' '));
