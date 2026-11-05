const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';

function paint(el, v) {
  el.querySelectorAll('.star').forEach(b => b.classList.toggle('on', +b.dataset.v <= v));
}

document.querySelectorAll('.stars').forEach(el => {
  paint(el, +el.dataset.mine || Math.round(parseFloat(el.querySelector('.avg b').textContent)) || 0);
  el.addEventListener('mouseover', e => e.target.dataset.v && paint(el, +e.target.dataset.v));
  el.addEventListener('mouseleave', () => paint(el, +el.dataset.mine || 0));
  el.addEventListener('click', async e => {
    const v = e.target.dataset.v;
    if (!v) return;
    if (el.dataset.anon) { location.href = '/accounts/login/?next='+encodeURIComponent(location.pathname+location.search); return; }
    const r = await fetch(el.dataset.url, {
      method: 'POST',
      headers: {'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'value=' + v,
    });
    const j = await r.json();
    if (!r.ok) { alert(j.error); return; }
    el.dataset.mine = j.mine;
    el.querySelector('.avg').innerHTML = `<b>${j.avg.toFixed(1)}</b> (${j.count})`;
    paint(el, j.mine);
  });
});

const q = document.getElementById('q'), dl = document.getElementById('sugs');
if (q && dl) {
  let t;
  q.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      if (q.value.trim().length < 2) return;
      const j = await (await fetch('/suggest/?q=' + encodeURIComponent(q.value))).json();
      dl.innerHTML = j.items.map(i => `<option value="${i.replace(/"/g, '&quot;')}">`).join('');
    }, 150);
  });
}

document.querySelectorAll('.review').forEach(card => {
  card.querySelectorAll('.vbtn').forEach(b => b.addEventListener('click', async () => {
    const v = b.dataset.v;
    if (v !== 'skip') {
      const r = await fetch(card.dataset.url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'verdict=' + v,
      });
      const j = await r.json();
      if (!r.ok) { alert(j.error); return; }
    }
    card.classList.add('done');
    setTimeout(() => card.remove(), 350);
  }));
});
