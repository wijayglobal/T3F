// Progressive enhancement for the server-rendered pages: star ratings, search autocomplete,
// the review queue and copy-on-focus snippets. No inline scripts (the CSP forbids them).
'use strict';

const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
const live = document.getElementById('live');

/** Read a message out to screen-reader users (and keep it visible to nobody else). */
function announce(text) {
  if (!live) return;
  live.textContent = '';
  // a new text node in a later frame makes repeated messages announce again
  requestAnimationFrame(() => { live.textContent = text; });
}

/** POST form fields; resolves to the JSON body, throws Error(message) on a failed request. */
async function postForm(url, fields) {
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken': csrf(),
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams(fields),
    });
  } catch {
    throw new Error('Network error. Please try again.');
  }
  let data = {};
  try { data = await res.json(); } catch { /* login redirects and server errors are not JSON */ }
  if (res.redirected && res.url.includes('/accounts/')) throw new Error('Please sign in and confirm your email first.');
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}

function loginUrl() {
  return '/accounts/login/?next=' + encodeURIComponent(location.pathname + location.search);
}

// ------------------------------------------------------------------ star ratings
function paint(el, v) {
  el.querySelectorAll('.star').forEach(b => b.classList.toggle('on', +b.dataset.v <= v));
}

function setMine(el, v) {
  el.dataset.mine = v;
  el.querySelectorAll('.star').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.v === v)));
  paint(el, v);
}

document.querySelectorAll('.stars').forEach(el => {
  const avgEl = el.querySelector('.avg b');
  const resting = () => +el.dataset.mine || Math.round(parseFloat(avgEl ? avgEl.textContent : '0')) || 0;
  paint(el, resting());

  const preview = e => { const v = e.target.dataset && e.target.dataset.v; if (v) paint(el, +v); };
  el.addEventListener('mouseover', preview);
  el.addEventListener('focusin', preview);
  el.addEventListener('mouseleave', () => paint(el, resting()));
  el.addEventListener('focusout', e => { if (!el.contains(e.relatedTarget)) paint(el, resting()); });

  el.addEventListener('click', async e => {
    const btn = e.target.closest('.star');
    if (!btn) return;
    if (el.dataset.anon) { location.href = loginUrl(); return; }
    try {
      const j = await postForm(el.dataset.url, {value: btn.dataset.v});
      setMine(el, j.mine);
      const avg = el.querySelector('.avg');
      avg.replaceChildren();
      const b = document.createElement('b');
      b.textContent = j.avg.toFixed(1);
      const sr = document.createElement('span');
      sr.className = 'sr-only';
      sr.textContent = ` average from ${j.count} ratings`;
      avg.append(b, ` (${j.count})`, sr);
      announce(`Rated ${j.mine} of 5. Average now ${j.avg.toFixed(1)} from ${j.count} ratings.`);
    } catch (err) {
      paint(el, resting());
      window.alert(err.message);  // alert dialogs are read out by screen readers too
    }
  });
});

// ------------------------------------------------------------------ search autocomplete
const q = document.getElementById('q'), dl = document.getElementById('sugs');
if (q && dl) {
  let timer, controller;
  q.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const term = q.value.trim();
      if (term.length < 2) return;
      if (controller) controller.abort();  // drop answers to older keystrokes
      controller = new AbortController();
      try {
        const res = await fetch('/suggest/?q=' + encodeURIComponent(term), {signal: controller.signal});
        if (!res.ok) return;
        const {items} = await res.json();
        dl.replaceChildren(...items.map(text => {
          const opt = document.createElement('option');
          opt.value = text;  // set as a property, never parsed as HTML
          return opt;
        }));
      } catch { /* aborted or offline: keep the old list */ }
    }, 150);
  });
}

// ------------------------------------------------------------------ review queue
document.querySelectorAll('.review').forEach(card => {
  card.querySelectorAll('.vbtn').forEach(btn => btn.addEventListener('click', async () => {
    const verdict = btn.dataset.v;
    if (verdict !== 'skip') {
      card.querySelectorAll('.vbtn').forEach(b => { b.disabled = true; });
      try {
        await postForm(card.dataset.url, {verdict});
      } catch (err) {
        card.querySelectorAll('.vbtn').forEach(b => { b.disabled = false; });
        window.alert(err.message);
        btn.focus();
        return;
      }
    }
    const en = card.querySelector('.pair .en'), ta = card.querySelector('.pair .ta');
    const label = verdict === 'accept' ? 'Marked correct' : verdict === 'reject' ? 'Marked incorrect' : 'Skipped';
    announce(en && ta ? `${label}: ${en.textContent} → ${ta.textContent}` : label);
    // Keep keyboard users in place: move focus to the same button on the next card.
    const next = card.nextElementSibling && card.nextElementSibling.classList.contains('review')
      ? card.nextElementSibling : null;
    card.classList.add('done');
    const focusTarget = next && (next.querySelector(`.vbtn[data-v="${verdict}"]`) || next.querySelector('.vbtn'));
    if (focusTarget) focusTarget.focus();
    else document.getElementById('main')?.focus();
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setTimeout(() => card.remove(), reduce ? 0 : 350);
  }));
});

// ------------------------------------------------------------------ copyable snippets
document.querySelectorAll('textarea.select-all').forEach(t => {
  t.addEventListener('focus', () => t.select());
  t.addEventListener('click', () => t.select());
});
