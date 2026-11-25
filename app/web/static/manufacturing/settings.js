window.manufacturingFeatures.push(() => ({
  storageKey() {
    return 'eve-manufacturing.settings.v1.' + (this.calculator ? 'calculator.' : '') + (this.demo ? 'demo' : 'live');
  },
  restoreSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey()));
      if (saved?.version !== 1 || !saved.form || typeof saved.form !== 'object' || Array.isArray(saved.form)) return;
      const form = this.getDefaultSettings();
      this.migrateBrokerSettings(saved.form);
      for (const [key, value] of Object.entries(saved.form)) {
        if (!(key in form)) continue;
        if (typeof form[key] === 'boolean' ? typeof value !== 'boolean' : !['string', 'number'].includes(typeof value)) return;
        form[key] = value;
      }
      if (saved.form.rigs === 'true') form.category = 'Rigs';
      else if (form.category === 'Ship and Module Modifications') form.category = 'Rigs';
      else if (form.category === 'Ship Equipment') form.category = 'Modules';
      this.hiddenColumns = Array.isArray(saved.hiddenColumns) ? saved.hiddenColumns.filter(id => this.columnOptions.some(c => c.id === id)) : [];
      if (this.calculator && Number.isInteger(Number(saved.blueprint?.type_id)) && Number(saved.blueprint.type_id) > 0 && typeof saved.blueprint.name === 'string') this.blueprint = {
        type_id: Number(saved.blueprint.type_id),
        name: saved.blueprint.name
      };
      this.form = form;
      this.profileSettings = saved.profileSettings && typeof saved.profileSettings === 'object' && !Array.isArray(saved.profileSettings) ? saved.profileSettings : {};
      this.profileId = typeof saved.profileId === 'string' ? saved.profileId : '';
      this.filtersOpen = saved.filtersOpen === true;
      this.page.offset = 0;
      return true;
    } catch (_) {
      /* Storage may be unavailable or contain an older invalid value. */
    }
  },
  saveSettings() {
    try {
      localStorage.setItem(this.storageKey(), JSON.stringify({
        version: 1,
        blueprint: this.calculator ? this.blueprint : undefined,
        hiddenColumns: this.hiddenColumns,
        form: this.form,
        profileSettings: this.profileSettings,
        profileId: this.profileId,
        filtersOpen: this.filtersOpen
      }));
    } catch (_) {
      this.storageWarning = 'Browser storage is unavailable. Changes will work, but may not survive a page reload.';
    }
  },
  migrateBrokerSettings(settings) {
    if (settings.broker_fee !== undefined) {
      settings.buy_broker_fee ??= settings.broker_fee;
      settings.sell_broker_fee ??= settings.broker_fee;
      delete settings.broker_fee;
    }
    return settings;
  },
}));
