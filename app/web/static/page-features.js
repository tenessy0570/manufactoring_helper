/* Copy descriptors so Alpine getters remain lazy and use the composed page state. */
window.composePage = (page, features) => {
  for (const create of features) {
    Object.defineProperties(page, Object.getOwnPropertyDescriptors(create()));
  }
  return page;
};
