const $=s=>document.querySelector(s);
const load=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))||d}catch{return d}};
const save=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch{}};
let recent=load('recent',[]),favs=load('favs',[]);
let WORDS=[];            // [tamil, roman, pos, [glosses]]
const MAX=50;
const mode=()=>document.querySelector('[name=mode]:checked').value;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

fetch('words.json').then(r=>r.json()).then(d=>{
  WORDS=d;$('#q').placeholder='Type a word… ('+d.length.toLocaleString()+' entries)';
}).catch(()=>render([],'Could not load words.json (serve the folder over http).'));

function score(w,q,m){
  if(m==='ta-en'){
    const t=w[0].replace(/^-/,'');
    if(t===q) return 0; if(t.startsWith(q)) return 2; return -1;
  }
  const re=new RegExp('(^|[^a-z])'+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'([^a-z]|$)');
  let best=-1;
  w[3].forEach((g,i)=>{
    const l=g.toLowerCase().replace(/^(to|a|an|the) /,'').replace(/[.;].*$/,'').trim();
    let s=-1;
    if(l===q) s=0;
    else if(l.startsWith(q)||l.split(/[,;] /).includes(q)) s=10;
    else if(re.test(g.toLowerCase())) s=30;
    if(s>=0){s+=i*2+w[3].length*0.5; if(best<0||s<best) best=s;}
  });
  return best;
}
function lookup(q,m){
  q=q.trim().toLowerCase(); if(!q) return [];
  if(m==='ta-en') q=q.normalize('NFC');
  const out=[];
  for(const w of WORDS){const s=score(w,q,m); if(s>=0) out.push([s,w]);}
  out.sort((a,b)=>a[0]-b[0]||a[1][0].length-b[1][0].length);
  return out.slice(0,MAX).map(x=>x[1]);
}
function render(rows,msg){
  const r=$('#results');
  if(!rows.length){r.innerHTML='<p class="msg">'+(msg||'No results found.')+'</p>';return}
  r.innerHTML='<table><tr><th>Tamil</th><th>Meaning</th><th></th></tr>'+rows.map(w=>
    `<tr><td><strong>${esc(w[0])}</strong><br><small>${esc(w[1])} ${w[2]?'· '+esc(w[2]):''}</small></td>
     <td class="m" title="Click to copy">${w[3].map(esc).join('<br>')}</td>
     <td><button class="star ${favs.includes(w[0])?'on':''}" data-w="${esc(w[0])}">★</button></td></tr>`).join('')+'</table>';
}
function showRecent(){
  $('#recentBox').hidden=!recent.length;
  $('#recent').innerHTML=recent.map(x=>`<a>${esc(x)}</a>`).join('');
}
function search(q){
  $('#q').value=q;
  const rows=lookup(q,mode()); render(rows);
  if(rows.length&&!recent.includes(q)){recent=[q,...recent].slice(0,8);save('recent',recent);showRecent()}
}
$('#form').addEventListener('submit',e=>{e.preventDefault();search($('#q').value)});
$('#recent').addEventListener('click',e=>{if(e.target.tagName==='A')search(e.target.textContent)});
$('#results').addEventListener('click',e=>{
  if(e.target.classList.contains('star')){
    const w=e.target.dataset.w;
    favs=favs.includes(w)?favs.filter(x=>x!==w):[...favs,w];save('favs',favs);e.target.classList.toggle('on');
  } else if(e.target.classList.contains('m')){
    navigator.clipboard?.writeText(e.target.innerText);
  }
});
$('#favLink').addEventListener('click',e=>{
  e.preventDefault();
  render(WORDS.filter(w=>favs.includes(w[0])),'No favourites yet.');
});
document.addEventListener('keydown',e=>{
  if(e.key==='/'&&document.activeElement!==$('#q')){e.preventDefault();$('#q').focus()}
});
let vlang='en-US';
$('#lang').addEventListener('click',()=>{
  vlang=vlang==='en-US'?'ta-IN':'en-US';$('#lang').textContent=vlang==='en-US'?'EN':'TA';
});
$('#mic').addEventListener('click',()=>{
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){alert('Voice search is not supported in this browser.');return}
  const r=new SR();r.lang=vlang;$('#mic').classList.add('on');
  r.onresult=e=>search(e.results[0][0].transcript);
  r.onend=()=>$('#mic').classList.remove('on');
  r.start();
});
showRecent();
