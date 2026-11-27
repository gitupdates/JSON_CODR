(function (global) {
  let primedToken = "";
  function readCookie(name) {
    const prefix = `${name}=`;
    const cookie = global.document?.cookie?.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
  }

  function csrfToken() {
    return readCookie("__Host-json_codr_csrf") || readCookie("json_codr_csrf");
  }

  function mutationHeaders(headers = {}) {
    const token = primedToken || csrfToken();
    return token ? { ...headers, "X-CSRF-Token": token } : { ...headers };
  }

  function websocketCsrfProtocol() {
    const token = primedToken || csrfToken();
    return token ? `json-codr-csrf.${token}` : "";
  }

  async function prime() {
    const response = await global.fetch("/api/identity/bootstrap", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Unable to initialize request security");
    const payload = await response.json();
    primedToken = typeof payload.csrf_token === "string" ? payload.csrf_token : "";
    return payload;
  }

  const api = { mutationHeaders, websocketCsrfProtocol, prime };
  global.JSONCodrHttpIdentity = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
