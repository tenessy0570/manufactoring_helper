window.manufacturingFeatures = [];
window.composeManufacturing = (page) => {
  for (const factory of window.manufacturingFeatures) {
    Object.defineProperties(page, Object.getOwnPropertyDescriptors(factory()));
  }
  return page;
};
