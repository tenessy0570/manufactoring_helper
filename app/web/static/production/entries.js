window.productionEntries = () => ({
  entry: {
    kind: 'invention',
    amount: '',
    comment: ''
  },
  editingId: null,
  resetEntry(kind = 'invention') {
    this.entry = {
      kind,
      amount: '',
      comment: ''
    };
    this.editingId = null;
    this.resetEstimate();
  },
  async saveEntry() {
    await this.action(async () => {
      const path = '/' + this.selected.id + '/entries' + (this.editingId ? '/' + this.editingId : '');
      this.replace(await this.api(path, this.editingId ? 'PUT' : 'POST', this.entry));
      const kind = this.entry.kind;
      this.resetEntry(kind);
      this.message = kind === 'income' ? 'Income added to total revenue.' : 'Expense saved.';
    });
  },
  editEntry(item) {
    this.editingId = item.id;
    this.entry = {
      kind: item.kind,
      amount: item.amount,
      comment: item.comment
    };
    this.resetEstimate();
    this.$nextTick(() => this.$refs.amount.focus());
  },
  async removeEntry(item) {
    if (!confirm('Delete this entry? Totals will be recalculated.')) return;
    await this.action(async () => {
      this.replace(await this.api('/' + this.selected.id + '/entries/' + item.id, 'DELETE'));
      if (this.editingId === item.id) this.resetEntry();
      this.message = 'Entry deleted.';
    });
  },
});
