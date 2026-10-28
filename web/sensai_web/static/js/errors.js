export class ApiError extends Error {
  constructor(code, message, { status = 0, hint = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.hint = hint;
  }
}

/** Builds an ApiError from a non-ok response ({"error":{code,message,hint}} body expected). */
export async function errorFromResponse(res) {
  let e = {};
  try { e = (await res.json()).error || {}; } catch { /* body is not JSON */ }
  const code = res.status === 409 ? 'tab_locked' : e.code || 'http';
  return new ApiError(code, e.message || `HTTP ${res.status}`, { status: res.status, hint: e.hint || null });
}
