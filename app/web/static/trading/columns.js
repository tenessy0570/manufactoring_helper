window.tradingColumns = () => ({
  hiddenColumns: [],
  columnOptions: [{
    id: 'route',
    label: 'Route'
  }, {
    id: 'jumps',
    label: 'Jumps'
  }, {
    id: 'jumpProfit',
    label: 'Profit / jump'
  }, {
    id: 'purchase',
    label: 'Buy / unit'
  }, {
    id: 'sale',
    label: 'Sell / unit'
  }, {
    id: 'profit',
    label: 'Profit / unit'
  }, {
    id: 'density',
    label: 'Profit / m3'
  }, {
    id: 'margin',
    label: 'Margin'
  }, {
    id: 'quantity',
    label: 'Units'
  }, {
    id: 'investment',
    label: 'Required investment'
  }, {
    id: 'cargo',
    label: 'Cargo volume'
  }, {
    id: 'batch',
    label: 'Batch profit'
  }, {
    id: 'turnover',
    label: 'Region turnover / day'
  }, {
    id: 'data',
    label: 'Data freshness'
  }],
  columnVisible(id) {
    return !this.hiddenColumns.includes(id);
  },
  restoreColumns() {
    try {
      const values = JSON.parse(localStorage.getItem('eve.interhub.columns.v1'));
      if (Array.isArray(values)) this.hiddenColumns = values.filter(id => this.columnOptions.some(c => c.id === id));
    } catch (_) {}
  },
  saveColumns() {
    try {
      localStorage.setItem('eve.interhub.columns.v1', JSON.stringify(this.hiddenColumns));
    } catch (_) {
      this.storageWarning = 'Column preferences could not be saved in this browser.';
    }
  },
  get tableWidth() {
    return Math.max(320, 230 + this.columnOptions.filter(c => this.columnVisible(c.id)).length * 100) + 'px';
  },
});
