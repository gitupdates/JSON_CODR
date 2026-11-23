(function (global) {
  function readCookie(name) {
    const prefix = `${name}=`;
    const cookie = global.document?.cookie?.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
  }

  function csrfToken() {
    return readCookie("__Host-json_codr_csrf") || readCookie("json_codr_csrf");
  }

  function mutationHeaders(headers = {}) {
    const token = csrfToken();
    return token ? { ...headers, "X-CSRF-Token": token } : { ...headers };
  }

  function websocketCsrfProtocol() {
    const token = csrfToken();
    return token ? `json-codr-csrf.${token}` : "";
  }

  const api = { mutationHeaders, websocketCsrfProtocol };
  global.JSONCodrHttpIdentity = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
