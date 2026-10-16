"""Dependency-free command palette over the build's published symbol catalog."""

JS = r"""
(function () {
  'use strict';
  var form = document.querySelector('.symsearch');
  if (!form) return;
  var fallback = form.querySelector('input'), trigger = form.querySelector('.command-trigger');
  var symbols = Array.from(form.querySelectorAll('datalist option')).map(function (option) {
    return {ticker: option.value, name: option.textContent};
  }).filter(function (row) { return /^[A-Z0-9.\-]{1,20}$/.test(row.ticker); });
  function href(row) { return form.dataset.base + encodeURIComponent(row.ticker) + '.html'; }
  function exact() {
    var match = symbols.find(function (row) { return row.ticker === fallback.value.trim().toUpperCase(); });
    if (match) location.assign(href(match));
  }
  fallback.addEventListener('change', exact);
  form.addEventListener('submit', function (event) { event.preventDefault(); exact(); });
  var dialog = document.getElementById('ticker-command');
  if (!dialog || typeof dialog.showModal !== 'function' || !trigger) return;
  var query = dialog.querySelector('input'), results = dialog.querySelector('[role="listbox"]');
  var status = dialog.querySelector('[role="status"]');
  var matches = [], selected = -1, returnFocus = trigger;
  function select(index, scroll) {
    selected = matches.length ? Math.max(0, Math.min(index, matches.length - 1)) : -1;
    Array.from(results.children).forEach(function (item, i) {
      item.setAttribute('aria-selected', String(i === selected));
    });
    var active = results.children[selected];
    if (active) {
      query.setAttribute('aria-activedescendant', active.id);
      if (scroll) active.scrollIntoView({block: 'nearest'});
    } else query.removeAttribute('aria-activedescendant');
  }
  function render() {
    var needle = query.value.trim().toUpperCase(), words = needle.split(/\s+/);
    var found = symbols.filter(function (row) {
      var text = row.ticker + ' ' + row.name.toUpperCase();
      return words.every(function (word) { return text.includes(word); });
    });
    function priority(row) { return row.ticker === needle ? 0 : row.ticker.startsWith(needle) ? 1 : 2; }
    found.sort(function (a, b) { return priority(a) - priority(b) || a.ticker.localeCompare(b.ticker); });
    matches = found.slice(0, 10);
    results.replaceChildren();
    matches.forEach(function (row, i) {
      var item = document.createElement('li'), ticker = document.createElement('strong'), name = document.createElement('span');
      item.id = 'command-option-' + i;
      item.setAttribute('role', 'option');
      item.dataset.index = i;
      ticker.textContent = row.ticker;
      name.textContent = row.name;
      item.append(ticker, name);
      results.appendChild(item);
    });
    select(0, false);
    results.scrollTop = 0;
    status.textContent = !found.length ? 'No matching ticker. Try a symbol or company name.' :
      'Showing ' + matches.length + ' of ' + found.length + ' matching tickers across published lists.';
  }
  function open() {
    if (dialog.open) { query.focus(); return; }
    returnFocus = document.activeElement;
    query.value = '';
    render();
    dialog.showModal();
    query.setAttribute('aria-expanded', 'true');
    query.focus();
  }
  trigger.addEventListener('click', open);
  dialog.querySelector('.command-close').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('keydown', function (event) {
    // A search input otherwise consumes the first Escape merely to clear its text.
    if (event.key === 'Escape' && !event.isComposing) { event.preventDefault(); dialog.close(); }
  });
  dialog.addEventListener('close', function () {
    query.setAttribute('aria-expanded', 'false');
    query.removeAttribute('aria-activedescendant');
    (returnFocus && returnFocus.isConnected ? returnFocus : trigger).focus({preventScroll: true});
  });
  dialog.addEventListener('click', function (event) {
    if (event.target !== dialog) return;
    var rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  document.addEventListener('keydown', function (event) {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'k' && !event.isComposing) {
      event.preventDefault();
      if (!event.repeat) open();
    }
  });
  query.addEventListener('input', render);
  query.addEventListener('keydown', function (event) {
    if (event.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      select(selected + (event.key === 'ArrowDown' ? 1 : -1), true);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (matches[selected]) location.assign(href(matches[selected]));
    }
  });
  results.addEventListener('pointerdown', function (event) { event.preventDefault(); });
  results.addEventListener('click', function (event) {
    var item = event.target.closest('[role="option"]');
    if (item && matches[Number(item.dataset.index)]) location.assign(href(matches[Number(item.dataset.index)]));
  });
  fallback.hidden = true;
  trigger.hidden = false;
})();
"""
