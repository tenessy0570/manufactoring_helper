window.readApiResponse = async (response) => {
  if (response.status >= 500) {
    throw new Error('The service is temporarily unavailable. Please try again.');
  }
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (_) {
    throw new Error('The service returned an invalid response. Please try again.');
  }
};
