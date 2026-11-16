/* Run in an isolated browser on /?demo=1 after Alpine has initialized. */
async function checkFrontendWorkflow() {
  const app = Alpine.$data(document.body);
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  check(app.demo, 'Browser scenarios require sample mode');
  check(!app.error && app.page.items.length > 0, 'Initial opportunities load');
  app.filtersOpen = true;
  await app.$nextTick();
  check([...document.querySelectorAll('[x-model^="form."]')].every(
    control => control.closest('form')?.id === 'opportunity-filters'
  ), 'All filters belong to one form');

  const originalHub = app.resultForm.hub_id;
  app.form.hub_id = originalHub === 'amarr' ? 'hek' : 'amarr';
  check(app.hasChanges && app.resultForm.hub_id === originalHub, 'Drafts do not relabel results');
  await app.load(true);
  check(app.hasChanges && app.resultForm.hub_id === originalHub, 'Reload preserves applied query');
  await app.load(false, 0);
  check(!app.hasChanges && app.resultForm.hub_id === app.form.hub_id, 'Apply updates result context');
  await app.$nextTick();
  check(document.querySelector('[aria-label="Trade hub"]').value === app.form.hub_id, 'Hub select shows actual selection');

  app.profileName = 'Browser check ' + Date.now();
  app.saveBrowserProfile();
  check(!app.profileError && app.browserProfile, 'Save named browser profile');
  app.form.tech = '2';
  app.updateBrowserProfile();
  app.form.tech = '1';
  await app.applyProfile();
  check(app.form.tech === '2', 'Update and reapply profile');
  app.form.category = 'Rigs';
  await app.load(false, 0);
  check(app.page.total === 1 && app.page.items[0].type_id === 31796, 'T2 rig selection');

  const row = document.querySelector('tbody tr');
  row.focus();
  await app.openItem(app.page.items[0]);
  await app.$nextTick();
  check(document.querySelector('main').inert, 'Dialog isolates background controls');
  app.$refs.dialog.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true}));
  check(document.activeElement.getAttribute('aria-label') === 'Close item details', 'Dialog traps Tab');
  window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
  await app.$nextTick();
  check(!app.selected && document.activeElement === row, 'Escape restores row focus');
  check(!document.body.style.overflow, 'Closing restores page scrolling');

  const previousPage = JSON.stringify(app.page);
  const originalApi = app.api;
  try {
    app.demo = false;
    app.api = async () => { throw new Error('Simulated network failure'); };
    await app.load(true, app.page.offset + app.page.limit);
    check(JSON.stringify(app.page) === previousPage, 'Failed pagination preserves rows and offset');
    check(app.error === 'Simulated network failure', 'Network error stays visible');
  } finally {
    app.demo = true;
    app.api = originalApi;
  }
  await app.load(false, 0);
  check(!app.error, 'Retry clears error after success');
  app.saveSettings();
  return 'PASS: filters, applied context, profile update, T2 rigs, keyboard dialog, network recovery';
}
