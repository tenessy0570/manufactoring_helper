window.manufacturingFeatures.push(() => ({
  blueprint: {
    type_id: '',
    name: ''
  },
  blueprintMatches: [],
  blueprintOpen: false,
  blueprintIndex: -1,
  blueprintSequence: 0,
  blueprintSearching: false,
  blueprintSearchDone: false,
  appliedBlueprintId: 0,
  invalidateBlueprint() {
    this.blueprint.type_id = '';
    this.blueprintMatches = [];
    this.blueprintIndex = -1;
    this.blueprintOpen = true;
    this.blueprintSearching = false;
    this.blueprintSearchDone = false;
    this.blueprintSequence++;
    this.requestSequence++;
    this.loading = false;
  },
  async searchBlueprint(force = false) {
    const seq = ++this.blueprintSequence;
    const name = this.blueprint.name.trim().replace(/\s+blueprint$/i, '').trim();
    if (name.length < 2 || (this.blueprint.type_id && !force)) return;
    this.blueprintSearching = true;
    this.blueprintSearchDone = false;
    try {
      const params = new URLSearchParams({
        search: name,
        limit: 50
      });
      const data = await this.requestApi('/api/v1/catalog/items?' + params);
      if (seq === this.blueprintSequence) {
        this.blueprintMatches = data.items;
        this.blueprintSearchDone = true;
        this.blueprintIndex = -1;
      }
    } catch (error) {
      if (seq === this.blueprintSequence) this.error = error.message;
    } finally {
      if (seq === this.blueprintSequence) this.blueprintSearching = false;
    }
  },
  chooseBlueprint(item) {
    this.requestSequence++;
    this.loading = false;
    this.blueprintSequence++;
    this.blueprintSearching = false;
    this.blueprint = {
      type_id: item.type_id,
      name: item.name + ' Blueprint'
    };
    this.blueprintOpen = false;
    this.blueprintIndex = -1;
    this.error = '';
    this.saveSettings();
  },
  async reopenBlueprint() {
    if (this.blueprint.name.trim().length < 2) return;
    this.blueprintOpen = true;
    if (!this.blueprintSearchDone || !this.blueprintMatches.length) await this.searchBlueprint(true);
  },
  blueprintKey(event) {
    if (event.key === 'Control') {
      if (!event.repeat) this.reopenBlueprint();
      return;
    }
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      this.blueprintOpen = true;
      if (!this.blueprintMatches.length) return;
      this.blueprintIndex = event.key === 'ArrowDown' ? Math.min(this.blueprintMatches.length - 1, this.blueprintIndex + 1) : Math.max(0, this.blueprintIndex - 1);
      this.$nextTick(() => document.getElementById('calculator-option-' + this.blueprintIndex)?.scrollIntoView({
        block: 'nearest'
      }));
    } else if (event.key === 'Enter' && this.blueprintOpen && this.blueprintMatches.length) {
      event.preventDefault();
      this.chooseBlueprint(this.blueprintMatches[Math.max(0, this.blueprintIndex)]);
    } else if (['Escape', 'Tab'].includes(event.key)) {
      this.blueprintOpen = false;
    }
  },
}));
