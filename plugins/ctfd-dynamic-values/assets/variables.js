/*
 * ctfd-dynamic-values — admin UI.
 *
 * Injects a "Variables" tab into the admin challenge page (next to Files/Flags/
 * Topics) and provides CRUD over per-challenge dynamic variables via the plugin
 * REST API. Vanilla JS, no framework — runs from register_admin_plugin_script.
 */
(function () {
  "use strict";

  // Only act on the admin challenge edit page, which defines CHALLENGE_ID.
  if (typeof window.CHALLENGE_ID === "undefined") return;

  var CHALLENGE_ID = window.CHALLENGE_ID;
  var ROOT = (window.init && window.init.urlRoot) || "";
  var NONCE = (window.init && window.init.csrfNonce) || "";
  var API = ROOT + "/api/v1/plugins/dynamic_values";

  function api(method, url, body) {
    return fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "CSRF-Token": NONCE,
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().catch(function () {
        return { success: false, errors: { "": "bad response" } };
      });
    });
  }

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (html !== undefined) e.innerHTML = html;
    return e;
  }

  function injectTab() {
    var nav = document.getElementById("challenge-properties");
    var content = document.getElementById("nav-tabContent");
    if (!nav || !content || document.getElementById("variables")) return false;

    var link = el("a", {
      "class": "nav-item nav-link small",
      "data-toggle": "tab",
      href: "#variables",
      role: "tab",
    }, "Variables");
    nav.appendChild(link);

    var pane = el("div", { "class": "tab-pane fade", id: "variables", role: "tabpanel" });
    pane.innerHTML =
      '<div class="row"><div class="col-md-12">' +
      '<h3 class="text-center py-3 d-block">Variables</h3>' +
      '<p class="text-muted small">Reference a variable in the challenge description (or a dynamic_formula flag) as <code>{{name}}</code>. ' +
      'Each participant gets a deterministic, stable value generated from the mask.</p>' +
      '<div id="dv-error" class="alert alert-danger" style="display:none"></div>' +
      '<table class="table table-striped"><thead><tr>' +
      '<th>Name</th><th>Mask</th><th>Scope</th><th>Salt</th><th>Preview</th><th></th>' +
      '</tr></thead><tbody id="dv-rows"></tbody></table>' +
      '<hr><h5>Add / edit variable</h5>' +
      '<form id="dv-form" class="form-inline" style="flex-wrap:wrap;gap:.5rem">' +
      '<input type="hidden" id="dv-id">' +
      '<input class="form-control" id="dv-name" placeholder="name (target_ip)" style="margin:.2rem">' +
      '<input class="form-control" id="dv-mask" placeholder="mask (10.{0-255}.{0-255}.{1-254})" style="margin:.2rem;min-width:280px">' +
      '<select class="form-control" id="dv-scope" style="margin:.2rem">' +
      '<option value="user">per-user</option>' +
      '<option value="team">per-team</option>' +
      '<option value="global">global</option></select>' +
      '<input class="form-control" id="dv-salt" placeholder="salt (optional)" style="margin:.2rem">' +
      '<button type="button" class="btn btn-secondary" id="dv-preview-btn" style="margin:.2rem">Preview</button>' +
      '<button type="submit" class="btn btn-success" id="dv-save-btn" style="margin:.2rem">Save</button>' +
      '<button type="button" class="btn btn-link" id="dv-reset-btn" style="margin:.2rem">Clear</button>' +
      '<span id="dv-preview" class="text-monospace ml-2" style="margin:.4rem"></span>' +
      '</form>' +
      '<details class="small text-muted mt-3"><summary>Mask token reference</summary>' +
      '<table class="table table-sm mt-2">' +
      '<tr><td><code>{A-B}</code></td><td>integer in [A, B]</td></tr>' +
      '<tr><td><code>{N}</code></td><td>N decimal digits</td></tr>' +
      '<tr><td><code>{xN}</code> / <code>{XN}</code></td><td>N hex chars (lower/upper)</td></tr>' +
      '<tr><td><code>{aN}</code> / <code>{AN}</code></td><td>N letters (lower/upper)</td></tr>' +
      '<tr><td><code>{wN}</code></td><td>N alphanumeric chars</td></tr>' +
      '<tr><td><code>\\{ \\}</code></td><td>literal braces</td></tr>' +
      '</table></details>' +
      '</div></div>';
    content.appendChild(pane);
    return true;
  }

  function showError(msg) {
    var box = document.getElementById("dv-error");
    if (!box) return;
    if (!msg) { box.style.display = "none"; box.textContent = ""; return; }
    box.style.display = "block";
    box.textContent = msg;
  }

  function rowsBody() { return document.getElementById("dv-rows"); }

  function renderRows(list) {
    var tb = rowsBody();
    tb.innerHTML = "";
    list.forEach(function (v) {
      var tr = el("tr");
      tr.innerHTML =
        "<td><code>{{" + escapeHtml(v.name) + "}}</code></td>" +
        "<td><code>" + escapeHtml(v.mask) + "</code></td>" +
        "<td>" + escapeHtml(v.scope) + "</td>" +
        "<td>" + escapeHtml(v.salt || "") + "</td>" +
        '<td class="text-monospace" data-prev="' + v.id + '"></td>' +
        '<td style="white-space:nowrap">' +
        '<button class="btn btn-sm btn-outline-primary dv-edit">edit</button> ' +
        '<button class="btn btn-sm btn-outline-danger dv-del">del</button></td>';
      tr.querySelector(".dv-edit").addEventListener("click", function () { fillForm(v); });
      tr.querySelector(".dv-del").addEventListener("click", function () { delVar(v.id); });
      tb.appendChild(tr);
      // async preview for this row
      previewMask(v.mask, v.salt, v.scope, v.name).then(function (val) {
        var cell = tb.querySelector('[data-prev="' + v.id + '"]');
        if (cell) cell.textContent = val;
      });
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function load() {
    showError("");
    api("GET", API + "?challenge_id=" + CHALLENGE_ID).then(function (resp) {
      if (resp.success) renderRows(resp.data || []);
      else showError("Failed to load variables");
    });
  }

  function fillForm(v) {
    document.getElementById("dv-id").value = v.id || "";
    document.getElementById("dv-name").value = v.name || "";
    document.getElementById("dv-mask").value = v.mask || "";
    document.getElementById("dv-scope").value = v.scope || "user";
    document.getElementById("dv-salt").value = v.salt || "";
    document.getElementById("dv-preview").textContent = "";
  }

  function resetForm() {
    fillForm({ scope: "user" });
    document.getElementById("dv-id").value = "";
  }

  function formData() {
    return {
      name: document.getElementById("dv-name").value.trim(),
      mask: document.getElementById("dv-mask").value,
      scope: document.getElementById("dv-scope").value,
      salt: document.getElementById("dv-salt").value,
    };
  }

  function save(ev) {
    ev.preventDefault();
    showError("");
    var id = document.getElementById("dv-id").value;
    var data = formData();
    var p;
    if (id) {
      p = api("PATCH", API + "/" + id, data);
    } else {
      data.challenge_id = CHALLENGE_ID;
      p = api("POST", API, data);
    }
    p.then(function (resp) {
      if (resp.success) { resetForm(); load(); }
      else showError(firstError(resp));
    });
  }

  function delVar(id) {
    if (!window.confirm("Delete this variable?")) return;
    api("DELETE", API + "/" + id).then(function () { load(); });
  }

  function firstError(resp) {
    if (resp && resp.errors) {
      var k = Object.keys(resp.errors)[0];
      return (k ? k + ": " : "") + resp.errors[k];
    }
    return "Request failed";
  }

  function previewMask(mask, salt, scope, name) {
    var q =
      API + "/preview?challenge_id=" + CHALLENGE_ID +
      "&mask=" + encodeURIComponent(mask || "") +
      "&salt=" + encodeURIComponent(salt || "") +
      "&scope=" + encodeURIComponent(scope || "user") +
      "&name=" + encodeURIComponent(name || "preview");
    return api("GET", q).then(function (r) {
      return r.success ? r.data.value : "(error)";
    });
  }

  function doPreview() {
    var d = formData();
    previewMask(d.mask, d.salt, d.scope, d.name || "preview").then(function (val) {
      document.getElementById("dv-preview").textContent = "→ " + val;
    });
  }

  function wire() {
    document.getElementById("dv-form").addEventListener("submit", save);
    document.getElementById("dv-preview-btn").addEventListener("click", doPreview);
    document.getElementById("dv-reset-btn").addEventListener("click", resetForm);
  }

  // The challenge page builds tabs after load; retry briefly until containers exist.
  var tries = 0;
  function boot() {
    if (injectTab()) {
      wire();
      load();
      return;
    }
    if (++tries < 40) setTimeout(boot, 100);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
