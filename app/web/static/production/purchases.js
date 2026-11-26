window.createProductionPurchases = () => ({
  purchaseRuns: '',
  purchaseText: '',
  purchaseNote: '',
  async prepareExpense(kind) {
    const units = Number(kind === 'invention' ? this.details.units : this.purchaseRuns);
    if (!Number.isInteger(units) || units < 1 || units > 1000000000) {
      this.error = kind === 'invention' ? 'Enter planned finished units in batch details.' : 'Enter manufacturing runs for this batch (1-1,000,000,000).';
      return;
    }
    this.resetEntry(kind);
    this.estimateUnits = kind === 'invention' ? String(units) : '';
    this.estimateRuns = kind === 'invention' ? '' : String(units);
    await this.$nextTick();
    await this.estimate();
    if (!this.error) this.$refs.amount.focus();
  },
  async copyMaterials(kind) {
    const units = Number(kind === 'invention' ? this.details.units : this.purchaseRuns);
    if (!Number.isInteger(units) || units < 1 || units > 1000000000) {
      this.error = kind === 'invention' ? 'Enter planned finished units in batch details.' : 'Enter manufacturing runs for this batch (1-1,000,000,000).';
      return;
    }
    await this.action(async () => {
      this.purchaseText = '';
      this.purchaseNote = '';
      const result = await this.requestApi('/' + this.selected.id + '/purchase-list', 'POST', {
        kind,
        ...(kind === 'invention' ? {
          units
        } : {
          manufacturing_runs: units
        }),
        hub_id: this.hub,
        decryptor_id: this.decryptorChoice === 'best' ? 'best' : this.decryptorChoice === 'none' ? null : Number(this.decryptorChoice)
      });
      if (!result.materials.length) throw Error('No purchase materials are available.');
      const params = new URLSearchParams();
      result.materials.forEach(item => params.append('type_ids', item.type_id));
      const response = await fetch('/api/v1/catalog/names?' + params, {
        credentials: 'same-origin'
      });
      if (response.status === 401) {
        location.assign('/login');
        throw Error('Please log in again.');
      }
      if (!response.ok) throw Error('Item names could not be loaded. Please retry.');
      const data = await window.readApiResponse(response);
      if (result.materials.some(item => !data.names[item.type_id])) throw Error('Some item names are unavailable. Please retry before copying.');
      this.purchaseText = result.materials.map(item => data.names[item.type_id] + '\t' + item.quantity).join('\n');
      this.purchaseNote = result.description + (result.stale ? ' Saved data is due for refresh.' : '');
      let copied = false;
      try {
        await navigator.clipboard.writeText(this.purchaseText);
        copied = true;
      } catch (_) {
        const area = document.createElement('textarea');
        area.value = this.purchaseText;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.append(area);
        area.select();
        try {
          copied = document.execCommand('copy');
        } catch (_) {}
        area.remove();
      }
      this.message = copied ? 'Materials copied. Paste into EVE Multibuy (Ctrl+V).' : 'Clipboard unavailable. Select and copy the list below.';
    });
  }
});
