window.productionBlueprint = () => ({
  searchText: '',
  typeId: null,
  matches: [],
  searchSequence: 0,
  activeMatch: -1,
  suggestionsOpen: false,
  invalidate() {
    this.typeId = null;
    this.matches = [];
    this.activeMatch = -1;
    this.suggestionsOpen = true;
    this.searchSequence++;
  },
  async search() {
    const seq = ++this.searchSequence;
    const text = this.searchText.trim().replace(/\s+blueprint$/i, '');
    if (this.typeId || text.length < 2) return;
    try {
      const r = await fetch('/api/v1/catalog/items?' + new URLSearchParams({
        search: text,
        limit: 50
      }), {
        credentials: 'same-origin'
      });
      if (r.status === 401) {
        location.assign('/login');
        return;
      }
      if (!r.ok) throw Error('Search unavailable. Retry.');
      const data = await window.readApiResponse(r);
      if (seq === this.searchSequence) this.matches = data.items;
    } catch (e) {
      if (seq === this.searchSequence) this.error = e.message;
    }
  },
  choose(item) {
    this.searchSequence++;
    this.typeId = item.type_id;
    this.searchText = item.name;
    this.suggestionsOpen = false;
  },
  searchKey(event) {
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      this.suggestionsOpen = true;
      this.activeMatch = event.key === 'ArrowDown' ? Math.min(this.matches.length - 1, this.activeMatch + 1) : Math.max(0, this.activeMatch - 1);
      this.$nextTick(() => document.getElementById('production-option-' + this.activeMatch)?.scrollIntoView({
        block: 'nearest'
      }));
    } else if (event.key === 'Enter' && this.suggestionsOpen && this.matches.length) {
      event.preventDefault();
      this.choose(this.matches[Math.max(this.activeMatch, 0)]);
    } else if (['Escape', 'Tab'].includes(event.key)) this.suggestionsOpen = false;
  },
});
