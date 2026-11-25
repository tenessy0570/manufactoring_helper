window.manufacturingFeatures.push(() => ({
  excludedItems: [],
  exclusionsOpen: false,
  excludedPage: 0,
  get excludedPageItems() {
    return this.excludedItems.slice(this.excludedPage * 25, this.excludedPage * 25 + 25);
  },
  get excludedPages() {
    return Math.max(1, Math.ceil(this.excludedItems.length / 25));
  },
  get visibleItems() {
    return this.page.items.filter(item => !this.excludedItems.some(v => v.type_id === item.type_id));
  },
  exclusionsKey() {
    return 'eve.opportunities.excluded.v1.' + (document.body.dataset.userId || 'preview') + (this.demo ? '.demo' : '');
  },
  exclusionsQueue: Promise.resolve(),
  usesServerExclusions() {
    return !this.demo && document.body.dataset.userId && document.body.dataset.userId !== 'preview';
  },
  async readExclusions() {
    let legacy = [];
    try {
      const saved = JSON.parse(localStorage.getItem(this.exclusionsKey()));
      if (Array.isArray(saved)) legacy = saved.filter(v => Number.isInteger(v.type_id) && v.type_id > 0 && typeof v.name === 'string').slice(0, 1000);
    } catch (_) {}
    if (!this.usesServerExclusions()) {
      this.excludedItems = legacy;
      return;
    }
    try {
      const data = await this.requestApi('/api/v1/opportunity-exclusions');
      this.excludedItems = data.items;
      if (legacy.length) {
        const merged = [...new Map([...data.items, ...legacy].map(v => [v.type_id, v])).values()].slice(0, 1000);
        const saved = await this.requestApi('/api/v1/opportunity-exclusions', {
          method: 'PUT',
          body: JSON.stringify({
            items: merged
          }),
          headers: {
            'Content-Type': 'application/json'
          }
        });
        this.excludedItems = saved.items;
        localStorage.removeItem(this.exclusionsKey());
      }
    } catch (_) {
      this.storageWarning = 'Could not load saved exclusions. Reload to retry.';
    }
  },
  async changeExclusions(next) {
    this.excludedPage = Math.min(this.excludedPage, Math.max(0, Math.ceil(next.length / 25) - 1));
    if (!this.usesServerExclusions()) {
      try {
        localStorage.setItem(this.exclusionsKey(), JSON.stringify(next));
        this.excludedItems = next;
      } catch (_) {
        this.storageWarning = 'Could not save excluded items.';
      }
      return;
    }
    this.excludedItems = next;
    this.exclusionsQueue = this.exclusionsQueue.catch(() => {}).then(async () => {
      try {
        await this.requestApi('/api/v1/opportunity-exclusions', {
          method: 'PUT',
          body: JSON.stringify({
            items: next
          }),
          headers: {
            'Content-Type': 'application/json'
          }
        });
      } catch (_) {
        this.storageWarning = 'Could not save exclusions. Reload before making further changes.';
      }
    });
    await this.exclusionsQueue;
  },
  async excludeItem(item) {
    if (this.excludedItems.some(v => v.type_id === item.type_id)) return;
    if (this.excludedItems.length >= 1000) {
      this.storageWarning = 'You can exclude up to 1000 items.';
      return;
    }
    await this.changeExclusions([...this.excludedItems, {
      type_id: item.type_id,
      name: item.name
    }]);
  },
  async restoreItem(typeId) {
    await this.changeExclusions(this.excludedItems.filter(v => v.type_id !== typeId));
  },
}));
