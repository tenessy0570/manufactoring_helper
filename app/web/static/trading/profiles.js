window.createTradingProfiles = () => ({
  profiles: [],
  profileId: '',
  profileName: '',
  profileError: '',
  profileSaveOpen: false,
  readProfiles() {
    try {
      const p = JSON.parse(localStorage.getItem('eve.interhub.profiles.v1'));
      this.profiles = Array.isArray(p) ? p.filter(p => typeof p.id === 'string' && typeof p.name === 'string' && p.form && typeof p.form === 'object' && !Array.isArray(p.form)) : [];
      this.profileId = localStorage.getItem('eve.interhub.profile.selected') || '';
    } catch (_) {}
  },
  persistProfiles(next) {
    try {
      localStorage.setItem('eve.interhub.profiles.v1', JSON.stringify(next));
      this.profiles = next;
      this.profileError = '';
      return true;
    } catch (_) {
      this.profileError = 'Could not save profiles. Allow browser storage and retry.';
      return false;
    }
  },
  selectProfile() {
    const p = this.profiles.find(p => p.id === this.profileId);
    if (p) {
      const form = this.getDefaultSettings();
      for (const k of Object.keys(form))
        if (typeof p.form[k] === typeof form[k]) form[k] = p.form[k];
      this.form = form;
      this.hiddenColumns = Array.isArray(p.hiddenColumns) ? p.hiddenColumns.filter(id => this.columnOptions.some(c => c.id === id)) : [];
      this.save();
    }
    try {
      localStorage.setItem('eve.interhub.profile.selected', this.profileId);
    } catch (_) {}
  },
  saveProfile(update = false) {
    const old = this.profiles.find(p => p.id === this.profileId),
      name = update ? old?.name : this.profileName.trim();
    if (!name || name.length > 100) {
      this.profileError = 'Enter a profile name (1-100 characters).';
      return;
    }
    if (!update && this.profiles.some(p => p.name.toLowerCase() === name.toLowerCase())) {
      this.profileError = 'A profile with this name already exists.';
      return;
    }
    const p = {
      id: update ? old.id : crypto.randomUUID(),
      name,
      form: JSON.parse(JSON.stringify(this.form)),
      hiddenColumns: [...this.hiddenColumns]
    };
    if (this.persistProfiles(update ? this.profiles.map(v => v.id === p.id ? p : v) : [...this.profiles, p])) {
      this.profileId = p.id;
      this.profileName = '';
      this.profileSaveOpen = false;
      try {
        localStorage.setItem('eve.interhub.profile.selected', p.id);
      } catch (_) {}
    }
  },
  deleteProfile() {
    const p = this.profiles.find(p => p.id === this.profileId);
    if (p && confirm('Delete profile ' + p.name + '? Current settings will be kept.') && this.persistProfiles(this.profiles.filter(v => v.id !== p.id))) {
      this.profileId = '';
      try {
        localStorage.removeItem('eve.interhub.profile.selected');
      } catch (_) {}
    }
  },
});
