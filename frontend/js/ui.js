/* KisanMitra — interactive, motion-free UI helpers.
 * Purely presentational: no API calls, no animation. Every feature degrades gracefully. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* Charts: draw instantly, no animation. */
  function initCharts() {
    if (window.Chart) {
      Chart.defaults.animation = false;
      Chart.defaults.transitions && Object.keys(Chart.defaults.transitions).forEach(k => {
        Chart.defaults.transitions[k] = { animation: { duration: 0 } };
      });
      const css = getComputedStyle(document.documentElement);
      Chart.defaults.color = css.getPropertyValue('--muted').trim() || '#9bb0a3';
      Chart.defaults.borderColor = css.getPropertyValue('--border').trim() || '#26392f';
    }
  }

  /* Mobile navigation: hamburger toggles the nav panel. */
  function initMenu() {
    const header = $('#header .header');
    const nav = header && $('nav', header);
    if (!nav || $('.km-menu-toggle', header)) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'km-menu-toggle';
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-label', 'Toggle navigation menu');
    btn.innerHTML = '<span aria-hidden="true">☰</span><span>Menu</span>';
    header.insertBefore(btn, nav);
    const set = open => {
      header.classList.toggle('km-nav-open', open);
      btn.setAttribute('aria-expanded', String(open));
      btn.firstElementChild.textContent = open ? '✕' : '☰';
    };
    btn.addEventListener('click', () => set(!header.classList.contains('km-nav-open')));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
    document.addEventListener('click', e => { if (!header.contains(e.target)) set(false); });
    nav.addEventListener('click', e => { if (e.target.closest('a')) set(false); });
    window.addEventListener('resize', () => { if (window.innerWidth > 1100) set(false); });
  }

  /* Re-sync chart colours after a theme switch. */
  document.addEventListener('km-theme-changed', initCharts);

  /* Back-to-top button (jumps instantly). */
  function initBackToTop() {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'km-top';
    b.hidden = true;
    b.textContent = '↑';
    b.setAttribute('aria-label', 'Back to top');
    b.addEventListener('click', () => window.scrollTo(0, 0));
    document.body.appendChild(b);
    const update = () => { b.hidden = window.scrollY < 480; };
    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* Show / hide password. */
  function initPasswordToggles() {
    $$('input[type="password"]').forEach(input => {
      if (input.parentElement.classList.contains('km-pw-wrap')) return;
      const wrap = document.createElement('div');
      wrap.className = 'km-pw-wrap';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      const t = document.createElement('button');
      t.type = 'button';
      t.className = 'km-pw-toggle';
      t.textContent = 'Show';
      t.setAttribute('aria-label', 'Show password');
      t.addEventListener('click', () => {
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        t.textContent = show ? 'Hide' : 'Show';
        t.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      });
      wrap.appendChild(t);
    });
  }

  /* Drag & drop an image onto the Crop Doctor upload area. */
  function initDropzone() {
    const area = $('.upload-area');
    const input = $('#imageInput');
    if (!area || !input) return;
    const stop = e => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter', 'dragover'].forEach(ev => area.addEventListener(ev, e => { stop(e); area.classList.add('km-dragover'); }));
    ['dragleave', 'drop'].forEach(ev => area.addEventListener(ev, e => { stop(e); area.classList.remove('km-dragover'); }));
    area.addEventListener('drop', e => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      try {
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (_) { /* browser without DataTransfer constructor: use the button */ }
    });
    // Paste an image from the clipboard as well.
    document.addEventListener('paste', e => {
      const item = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith('image/'));
      const file = item && item.getAsFile();
      if (!file) return;
      try {
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (_) {}
    });
  }

  /* Click a table header to sort that column (numbers, dates and text). */
  function sortValue(text) {
    const t = text.trim().replace(/[₹,\s]/g, '');
    if (t !== '' && !isNaN(Number(t))) return Number(t);
    const d = Date.parse(text);
    return isNaN(d) ? text.trim().toLowerCase() : d;
  }
  function initSortableTables() {
    document.addEventListener('click', e => {
      const th = e.target.closest('th');
      const table = th && th.closest('table');
      if (!table || !table.tBodies[0]) return;
      const index = Array.from(th.parentNode.children).indexOf(th);
      const asc = th.getAttribute('aria-sort') !== 'ascending';
      const rows = Array.from(table.tBodies[0].rows).filter(r => r.cells.length > index && r.cells.length > 1);
      if (rows.length < 2) return;
      rows.sort((a, b) => {
        const x = sortValue(a.cells[index].textContent), y = sortValue(b.cells[index].textContent);
        return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1);
      });
      rows.forEach(r => table.tBodies[0].appendChild(r));
      $$('th', table).forEach(h => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    });
    // Mark headers as sortable whenever tables are (re)rendered.
    const mark = () => $$('table th:not(.km-sortable)').forEach(th => {
      th.classList.add('km-sortable');
      th.setAttribute('title', 'Click to sort');
    });
    mark();
    new MutationObserver(mark).observe(document.body, { childList: true, subtree: true });
  }

  /* Live search box on the My Reports page. */
  function initReportSearch() {
    const list = $('#reportsList');
    if (!list || $('#kmReportSearch')) return;
    const box = document.createElement('input');
    box.id = 'kmReportSearch';
    box.type = 'search';
    box.placeholder = 'Search your reports…';
    box.setAttribute('aria-label', 'Search your reports');
    list.parentNode.insertBefore(box, list);
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.hidden = true;
    empty.textContent = 'No reports match your search.';
    list.parentNode.insertBefore(empty, list.nextSibling);
    const apply = () => {
      const q = box.value.trim().toLowerCase();
      let shown = 0;
      Array.from(list.children).forEach(card => {
        const hit = !q || card.textContent.toLowerCase().includes(q);
        card.hidden = !hit;
        if (hit) shown++;
      });
      empty.hidden = shown > 0 || list.children.length === 0;
    };
    box.addEventListener('input', apply);
    new MutationObserver(apply).observe(list, { childList: true });
  }

  /* Character counters on long text boxes. */
  function initCounters() {
    $$('textarea[maxlength]').forEach(t => {
      if (t.nextElementSibling && t.nextElementSibling.classList.contains('km-counter')) return;
      const c = document.createElement('div');
      c.className = 'km-counter';
      c.setAttribute('aria-hidden', 'true');
      const update = () => { c.textContent = t.value.length + ' / ' + t.maxLength; };
      t.addEventListener('input', update);
      t.form && t.form.addEventListener('reset', () => setTimeout(update));
      t.parentNode.insertBefore(c, t.nextSibling);
      update();
    });
  }

  /* Ctrl/Cmd + Enter sends chat messages; Enter alone keeps a new line. */
  function initChatShortcuts() {
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' || !(e.ctrlKey || e.metaKey)) return;
      const t = e.target;
      if (!(t instanceof HTMLTextAreaElement) || !t.form) return;
      if (t.id === 'chatInput' || t.id === 'chatMessageInput') {
        e.preventDefault();
        t.form.requestSubmit();
      }
    });
  }

  /* Keep the newest chat message in view. */
  function initChatAutoScroll() {
    ['chatMessages'].forEach(id => {
      const box = document.getElementById(id);
      if (!box) return;
      new MutationObserver(() => { box.scrollTop = box.scrollHeight; }).observe(box, { childList: true, subtree: true, characterData: true });
    });
  }

  /* Pressing Enter in a filter row triggers its primary button. */
  function initFilterEnter() {
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
      const row = e.target.closest('.filter-row');
      if (!row || e.target.closest('form')) return;
      const btn = $('.btn:not(.outline)', row) || $('.btn', row);
      if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
    });
  }

  function init() {
    document.body.classList.add('km-ui');
    initCharts();
    initBackToTop();
    initPasswordToggles();
    initDropzone();
    initSortableTables();
    initReportSearch();
    initCounters();
    initChatShortcuts();
    initChatAutoScroll();
    initFilterEnter();
    if ($('#header .header')) initMenu();
    else document.addEventListener('km-header-ready', initMenu, { once: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
