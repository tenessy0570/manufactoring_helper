window.manufacturingFeatures.push(() => ({
  deletingProfile: false,
  profileId: '',
  profiles: [],
  profileSettings: {},
  profileSaveOpen: false,
  profileName: '',
  profileError: '',
  profileWarning: '',
  profileNotice: '',
  browserProfilesKey() {
    return this.storageKey() + '.profiles';
  },
  readBrowserProfiles() {
    try {
      const values = JSON.parse(localStorage.getItem(this.browserProfilesKey()));
      return Array.isArray(values) ? values.filter(p => p?.browser === true && typeof p.id === 'string' && typeof p.name === 'string' && p.form && typeof p.form === 'object' && !Array.isArray(p.form)) : [];
    } catch (_) {
      return [];
    }
  },
  saveBrowserProfile() {
    this.profileError = '';
    const name = this.profileName.trim();
    if (!name || name.length > 100) {
      this.profileError = 'Enter a profile name (1-100 characters).';
      return;
    }
    const current = this.profiles.filter(p => p.browser);
    if (current.some(p => p.name.toLowerCase() === name.toLowerCase())) {
      this.profileError = 'A browser profile with this name already exists.';
      return;
    }
    const profile = {
      id: 'browser:' + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)),
      name,
      browser: true,
      form: JSON.parse(JSON.stringify(this.form)),
      settings: JSON.parse(JSON.stringify(this.profileSettings))
    };
    try {
      localStorage.setItem(this.browserProfilesKey(), JSON.stringify([...current, profile]));
    } catch (_) {
      this.profileError = 'Could not save this profile. Allow browser storage and try again.';
      return;
    }
    this.profiles = [profile, ...this.profiles];
    this.profileId = profile.id;
    this.profileSaveOpen = false;
    this.profileName = '';
    this.profileNotice = 'Profile saved in this browser.';
    this.saveSettings();
  },
  setProfile(profile) {
    if (profile.browser) this.migrateBrokerSettings(profile.form);
    else this.migrateBrokerSettings(profile.settings);
    if (profile.browser) {
      this.form = Object.fromEntries(Object.entries(this.getDefaultSettings()).map(([key, value]) => [key, profile.form[key] ?? value]));
      this.profileSettings = JSON.parse(JSON.stringify(profile.settings || {}));
      return;
    }
    const s = profile.settings;
    this.profileSettings = JSON.parse(JSON.stringify(s));
    this.form = {
      ...this.getDefaultSettings()
    };
    for (const key of Object.keys(this.form))
      if (s[key] !== null && s[key] !== undefined) this.form[key] = s[key];
    this.form.tech = s.meta_group_ids?.length === 1 ? String(s.meta_group_ids[0]) : s.meta_group_ids?.length ? '__profile__' : '';
    this.form.category = s.is_rig === true ? 'Rigs' : s.categories?.length === 1 ? (s.categories[0] === 'Ship Equipment' ? 'Modules' : s.categories[0] === 'Ship and Module Modifications' ? 'Rigs' : s.categories[0]) : s.categories?.length || s.is_rig === false ? '__profile__' : '';
    this.form.limit = String(s.limit);
  },
  async applyProfile() {
    const profile = this.profiles.find(p => p.id === this.profileId);
    this.profileNotice = '';
    if (profile) this.setProfile(profile);
    else {
      this.profileSettings = {};
      this.form = this.getDefaultSettings();
    }
    await this.load(false, 0);
  },
  get selectedProfile() {
    return this.profiles.find(p => p.id === this.profileId);
  },
  async deleteProfile() {
    const profile = this.selectedProfile;
    if (!profile || this.deletingProfile) return;
    if (profile.browser) {
      this.deleteBrowserProfile();
      return;
    }
    if (!confirm('Delete profile "' + profile.name + '"? Current settings will be kept.')) return;
    this.deletingProfile = true;
    this.error = '';
    try {
      await this.requestApi('/api/v1/profiles/' + encodeURIComponent(profile.id), {
        method: 'DELETE'
      });
      this.profiles = this.profiles.filter(p => p.id !== profile.id);
      this.profileId = '';
      this.profileNotice = 'Profile deleted. Current settings kept.';
      this.saveSettings();
      try {
        const result = await this.requestApi('/api/v1/profiles');
        this.profiles = [...this.profiles.filter(p => p.browser), ...result.items];
      } catch (_) {
        this.profileWarning = 'Profile deleted. Reload to refresh the remaining server profiles.';
      }
    } catch (error) {
      this.error = error.message;
    } finally {
      this.deletingProfile = false;
    }
  },
  get browserProfile() {
    return this.profiles.find(p => p.id === this.profileId && p.browser);
  },
  updateBrowserProfile() {
    const previous = this.browserProfile;
    if (!previous) return;
    const replacement = {
      ...previous,
      form: JSON.parse(JSON.stringify(this.form)),
      settings: JSON.parse(JSON.stringify(this.profileSettings))
    };
    const next = this.profiles.map(p => p.id === previous.id ? replacement : p);
    try {
      localStorage.setItem(this.browserProfilesKey(), JSON.stringify(next.filter(p => p.browser)));
    } catch (_) {
      this.profileError = 'Could not update this profile. Allow browser storage and retry.';
      this.profileSaveOpen = true;
      return;
    }
    this.profiles = next;
    this.profileNotice = 'Profile updated.';
    this.saveSettings();
  },
  deleteBrowserProfile() {
    const profile = this.browserProfile;
    if (!profile || !confirm('Delete browser profile "' + profile.name + '"? Current filters will be kept.')) return;
    const next = this.profiles.filter(p => p.id !== profile.id);
    try {
      localStorage.setItem(this.browserProfilesKey(), JSON.stringify(next.filter(p => p.browser)));
    } catch (_) {
      this.profileError = 'Could not delete this profile. Allow browser storage and retry.';
      this.profileSaveOpen = true;
      return;
    }
    this.profiles = next;
    this.profileId = '';
    this.profileNotice = 'Profile deleted. Current filters kept.';
    this.saveSettings();
  },
}));
