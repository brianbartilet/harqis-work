(() => {
  "use strict";
  const $ = (s) => document.querySelector(s),
    el = (tag, text, cls) => {
      const n = document.createElement(tag);
      if (text !== undefined) n.textContent = text;
      if (cls) n.className = cls;
      return n;
    };
  let offset = 0,
    total = 0,
    currentFile = null,
    currentPackage = null,
    categories = [],
    sources = [],
    view = "catalog",
    automaticScans = false;
  const pendingScans = new Map();
  const selected = new Set(),
    pageSize = 50;
  function requestId() {
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
    return [
      h.slice(0, 8),
      h.slice(8, 12),
      h.slice(12, 16),
      h.slice(16, 20),
      h.slice(20),
    ].join("-");
  }
  const date = (v) => (v ? new Date(v * 1000).toLocaleString() : "—"),
    size = (v) =>
      v == null
        ? "—"
        : v < 1024
          ? `${v} B`
          : `${(v / 1024 ** (v >= 1048576 ? 2 : 1)).toFixed(1)} ${v >= 1048576 ? "MB" : "KB"}`;
  const list = (s) =>
      s
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    catName = (id) =>
      categories.find((c) => String(c.id) === String(id))?.name || id;
  function message(text, error = false) {
    $("#files-message").textContent = text;
    $("#files-message").classList.toggle("error", error);
  }
  async function api(path, body, method) {
    const r = await fetch("/files/api/" + path, {
      method: method || (body ? "POST" : "GET"),
      headers: { "Content-Type": "application/json", "X-Harqis-Files": "1" },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data;
    try {
      data = await r.json();
    } catch {
      throw Error("Server returned an unreadable response");
    }
    if (!r.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
      );
    return data;
  }
  const safe =
    (fn) =>
    async (...a) => {
      try {
        await fn(...a);
      } catch (e) {
        message(e.message, true);
      }
    };
  function button(text, fn) {
    const b = el("button", text);
    b.type = "button";
    b.onclick = safe(fn);
    return b;
  }
  function link(text, url) {
    const a = el("a", text);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }
  function selection() {
    $("#selected-count").textContent = `${selected.size} selected`;
    $("#package-selection").textContent =
      `${selected.size} files selected in the catalog.`;
    $("#selection-package").disabled = !selected.size;
    $("#package-form button[type=submit], #package-form button:not([type])").disabled = !selected.size;
  }
  function filters() {
    return new URLSearchParams(new FormData($("#filter-files")));
  }
  async function changeView(name) {
    message("");
    view = name;
    document
      .querySelectorAll('[id^="view-"]')
      .forEach((n) => (n.hidden = n.id !== `view-${name}`));
    document
      .querySelectorAll("[data-view]")
      .forEach((n) =>
        n.setAttribute("aria-pressed", String(n.dataset.view === name)),
      );
    selection();
    await refresh();
  }
  async function catalog() {
    const params = filters();
    params.set("offset", offset);
    const result = await api("catalog?" + params);
    total = result.total;
    const body = $("#file-rows");
    body.replaceChildren();
    for (const f of result.items) {
      const tr = el("tr"),
        check = el("input");
      check.type = "checkbox";
      check.checked = selected.has(f.id);
      check.setAttribute("aria-label", "Select " + f.name);
      check.onchange = () => {
        check.checked ? selected.add(f.id) : selected.delete(f.id);
        selection();
      };
      const td = el("td");
      td.append(check);
      tr.append(td);
      const name = el("td"),
        b = button(f.name, () => detail(f.id));
      b.className = "file-name";
      name.append(b, el("div", f.mime_type, "files-muted"));
      tr.append(name);
      const tags = el("td");
      [...(f.categories || []).map(catName), ...(f.tags || [])].forEach((t) =>
        tags.append(el("span", t, "files-pill")),
      );
      tr.append(tags);
      const loc = el("td");
      for (const l of f.locations)
        loc.append(
          el(
            "div",
            `${sources.find((s) => s.id === l.source_id)?.name || "Source"} · ${l.status.replaceAll("_", " ")}`,
            "files-muted",
          ),
        );
      tr.append(
        loc,
        el("td", size(f.size)),
        el("td", date(f.last_seen), "files-muted"),
      );
      body.append(tr);
    }
    if (!result.items.length) {
      const tr = el("tr"),
        td = el("td", "No matching files.");
      td.colSpan = 6;
      tr.append(td);
      body.append(tr);
    }
    $("#file-count").textContent =
      total ? `${total} files · ${offset + 1}–${Math.min(offset + pageSize, total)}` : "0 files";
    $("#previous-page").disabled = offset === 0;
    $("#next-page").disabled = offset + pageSize >= total;
    selection();
    const empty = $("#catalog-empty");
    empty.hidden = result.items.length > 0;
    $("#catalog-table").hidden = !result.items.length;
    $("#catalog-pages").hidden = !result.items.length;
    empty.replaceChildren();
    if (!empty.hidden) {
      const filtered = [...filters().values()].some(Boolean);
      empty.append(el("h2", filtered ? "No files match these filters" : "Your catalog is ready for its first files"));
      if (filtered) {
        empty.append(el("p", "Try another name, category, or availability.", "files-muted"), button("Clear filters", async () => {
          $("#filter-files").reset(); offset = 0; await catalog();
        }));
      } else {
        empty.append(el("p", sources.length ? "Browse a server folder to choose files, or scan a location to index its contents." : "No locations are connected yet. Connect remote storage, or configure a server folder in Locations.", "files-muted"));
        const local = localSources();
        for (const source of local) {
          const row = el("div", undefined, "files-empty-location");
          const info = el("div");
          info.append(el("strong", source.name), el("p", source.root, "files-path"), el("p", sourceStatus(source), "files-muted"));
          row.append(info, button("Browse " + source.name, () => openPicker(source.id)));
          if (source.enabled) {
            const scanButton = button("Scan " + source.name, () => queueScan(source.id));
            scanButton.disabled = source.state === "scanning" || pendingScans.has(source.id);
            row.append(scanButton);
          }
          empty.append(row);
        }
        empty.append(button("Manage locations", () => changeView("sources")));
      }
    }
  }
  function localSources() {
    return sources.filter((s) => s.kind === "local" && s.host?.toLowerCase() === $("#files-app").dataset.host.toLowerCase() && s.configured_available !== false);
  }
  async function loadSources() {
    const data = await api("sources");
    sources = data.items;
    automaticScans = data.automatic_scans;
    for (const s of sources) {
      const since = pendingScans.get(s.id);
      if (since && (s.last_scan >= since || s.last_attempt >= since || Date.now() / 1000 - since > 120)) pendingScans.delete(s.id);
    }
  }
  function sourceStatus(s) {
    if (s.configured_available === false) return "Folder removed from server configuration";
    if (!s.enabled) return s.kind === "local" ? "Automatic scans paused · browsing is still available" : "Scans paused";
    if (s.state === "scanning") return "Scanning files…";
    if (pendingScans.has(s.id)) return "Scan queued · waiting for the worker";
    return ({new: "Ready for the first scan", ready: "Ready", missing: "Folder unavailable — check the server drive", permission_denied: "Access denied — check the connection permissions", unreachable: "Cannot reach this location — check its connection"})[s.state] || s.state;
  }
  async function queueScan(id) {
    await api(`sources/${id}/scan`, {});
    pendingScans.set(id, Date.now() / 1000);
    message("Scan queued. Files will appear here as they are discovered.");
    await refresh();
  }
  function sourceOptions() {
    const select = $("#reference-form [name=source_id]");
    select.replaceChildren(
      ...sources.map((s) => {
        const o = el("option", s.name);
        o.value = s.id;
        return o;
      }),
    );
    $("#reference-form button").disabled = !sources.length;
    referenceHelp();
  }
  function categoryOptions(select, values = [], all = false) {
    select.replaceChildren();
    if (all) {
      const option = el("option", "All categories");
      option.value = "";
      select.append(option);
    }
    for (const c of [
      ...categories,
      ...values
        .filter((id) => !categories.some((c) => String(c.id) === String(id)))
        .map((id) => ({ id, name: "Archived category " + id })),
    ]) {
      const o = el("option", c.name);
      o.value = String(c.id);
      o.selected = values.map(String).includes(String(c.id));
      select.append(o);
    }
  }
  let folderPath = "", folderOffset = 0, pickerRequest = 0;
  const picked = new Set();
  const folderSafe = (fn) => async (...args) => {
    try { await fn(...args); }
    catch (error) { $("#folder-message").textContent = error.message; }
  };
  function pickerSelection() {
    $("#folder-selection").textContent = `${picked.size} ${picked.size === 1 ? "file" : "files"} selected`;
    $("#add-picked").disabled = !picked.size;
  }
  async function openPicker(sourceId) {
    await loadSources();
    const local = localSources();
    if (!local.length) {
      await changeView("sources");
      message("No server folders are configured. Add remote storage here, or configure a server folder first.");
      return;
    }
    const select = $("#folder-source");
    select.replaceChildren(...local.map((s) => {
      const option = el("option", `${s.name} — ${s.root}`);
      option.value = s.id; return option;
    }));
    select.value = local.some((s) => s.id === sourceId) ? sourceId : local[0].id;
    picked.clear(); pickerSelection();
    folderPath = ""; folderOffset = 0;
    $("#folder-dialog").showModal();
    await folderSafe(loadFolder)();
  }
  async function loadFolder() {
    const request = ++pickerRequest;
    $("#folder-message").textContent = "Loading folder…";
    $("#folder-entries").replaceChildren();
    $("#folder-previous").disabled = true;
    $("#folder-next").disabled = true;
    const id = $("#folder-source").value;
    const data = await api(`sources/${id}/browse?` + new URLSearchParams({path: folderPath, offset: folderOffset}));
    if (request !== pickerRequest) return;
    $("#folder-message").textContent = data.items.length ? "Select files to add them to your catalog and package selection." : "This folder is empty.";
    const crumbs = $("#folder-breadcrumbs");
    crumbs.replaceChildren();
    const navigate = (path) => folderSafe(async () => { folderPath = path; folderOffset = 0; await loadFolder(); });
    crumbs.append(button(sources.find((s) => s.id === id)?.name || "Root folder", navigate("")));
    const parts = data.path ? data.path.split("/") : [];
    parts.forEach((part, index) => crumbs.append(el("span", "/", "files-muted"), button(part, navigate(parts.slice(0, index + 1).join("/")))));
    for (const item of data.items) {
      const row = el("div", undefined, "files-folder-row");
      if (item.kind === "folder") {
        const open = button(item.name, navigate(item.path));
        open.setAttribute("aria-label", "Open folder " + item.name);
        row.append(el("span", "Folder", "files-muted"), open);
      } else {
        const label = el("label"), check = el("input");
        check.type = "checkbox"; check.checked = picked.has(item.path);
        check.onchange = () => {
          if (check.checked && picked.size >= 200) {
            check.checked = false;
            $("#folder-message").textContent = "Add up to 200 files at a time."; return;
          }
          check.checked ? picked.add(item.path) : picked.delete(item.path);
          pickerSelection();
        };
        label.append(check, el("span", item.name));
        row.append(label, el("span", size(item.size), "files-muted"));
      }
      $("#folder-entries").append(row);
    }
    $("#folder-previous").disabled = folderOffset === 0;
    $("#folder-next").disabled = folderOffset + 100 >= data.total;
    $("#folder-page").textContent = data.total ? `${folderOffset + 1}–${Math.min(folderOffset + 100, data.total)} of ${data.total}` : "0 items";
  }
  function sourceHelp() {
    const kind = $("#source-form [name=kind]").value;
    const guidance = {
      drive: ["Google Drive folder link or ID", "Paste a Google Drive folder link. The server’s connected Google account must have access."],
      sftp: ["Remote folder path", "Enter the full remote folder path and the connection profile configured on the server."],
      http: ["Direct file URL", "Use a public HTTP(S) file URL without query parameters. Add one file per location."],
      local: ["Server subfolder path", "Use a full path inside a configured server folder. This is a folder on the server, not on your computer."],
      ftp: ["FTP location", "FTP supports manual references only. Use SFTP to scan or retrieve files."],
    }[kind];
    $("#source-root-label").textContent = guidance[0];
    $("#source-help").textContent = guidance[1];
    $("#sftp-profile-field").hidden = kind !== "sftp";
    $("#source-form [name=profile]").required = kind === "sftp";
  }
  function referenceHelp() {
    const s = sources.find((s) => s.id === $("#reference-form [name=source_id]").value);
    $("#reference-help").textContent = !s ? "Add a location first, or use Browse folders for configured server files." : s.kind === "local" ? `Enter the full server file path inside ${s.root}. Browse folders checks that files exist before adding them.` : s.kind === "drive" ? "Enter the Drive file ID, not a folder ID." : `Enter the complete file location for ${s.name}. Availability is checked when the file is retrieved.`;
    $("#reference-locator-label").textContent = s?.kind === "local" ? "Full server file path" : s?.kind === "drive" ? "Drive file ID" : "File location";
  }
  async function detail(id) {
    currentFile = id;
    const f = await api("files/" + id);
    await api("files/" + id + "/opened", {});
    const box = $("#file-detail");
    box.replaceChildren(
      el("h2", f.name),
      el("p", `${f.mime_type} · ${size(f.size)}`, "files-muted"),
    );
    box.append(link("Download file", "/files/api/files/" + id + "/download"));
    box.append(
      el(
        "p",
        `Last seen: ${date(f.last_seen)} · Downloaded: ${date(f.last_downloaded)} · Opened: ${date(f.last_opened)}`,
        "files-muted",
      ),
    );
    for (const l of f.locations) {
      const section = el("div", undefined, "files-panel");
      section.append(
        el("strong", l.status.replaceAll("_", " ")),
        el("p", l.locator, "files-path"),
      );
      if (l.error) section.append(el("p", l.error, "files-muted"));
      box.append(section);
    }
    categoryOptions($("#metadata-form [name=categories]"), f.categories || []);
    $("#metadata-form [name=tags]").value = (f.tags || []).join(", ");
    $("#metadata-form [name=entities]").value = (f.entities || []).join(", ");
    const select = $("#location-form [name=source_id]");
    select.replaceChildren(
      ...sources.map((s) => {
        const o = el("option", s.name);
        o.value = s.id;
        return o;
      }),
    );
    if (!$("#file-dialog").open) $("#file-dialog").showModal();
  }
  async function sourceList() {
    $("#scan-mode").textContent = automaticScans ? "Automatic scans are enabled. New locations are picked up by the scheduler." : "Automatic scans are off on this server. Browse folders or use Scan now to add files.";
    const box = $("#source-list");
    box.replaceChildren();
    for (const s of sources) {
      const card = el("article", undefined, "files-panel");
      card.append(
        el("h2", s.name),
        el("p", `${({local: "Server folder", drive: "Google Drive", sftp: "SFTP", http: "Web file", ftp: "FTP reference"})[s.kind]}${s.configured_root ? " · From server settings" : ""}`, "files-muted"),
        el("p", sourceStatus(s)),
        el("p", s.root, "files-path"),
        el(
          "p",
          `Every ${s.interval_hours} hours · Last scan ${date(s.last_scan)}${s.error ? " · " + s.error : ""}`,
          "files-muted",
        ),
      );
      if (localSources().some((item) => item.id === s.id)) card.append(button("Browse files", () => openPicker(s.id)));
      if (s.kind !== "ftp" && s.configured_available !== false) {
        const scanButton = button("Scan now", () => queueScan(s.id));
        scanButton.disabled = !s.enabled || s.state === "scanning" || pendingScans.has(s.id);
        card.append(scanButton);
      }
      card.append(
        button(s.enabled ? "Pause scans" : "Resume scans", async () => {
          const data = Object.fromEntries(
            [
              "name",
              "kind",
              "root",
              "host",
              "profile",
              "interval_hours",
              "categories",
              "tags",
            ].map((k) => [k, s[k]]),
          );
          data.enabled = !s.enabled;
          await api("sources/" + s.id, data, "PUT");
          await refresh();
        }),
      );
      box.append(card);
    }
    if (!sources.length)
      box.append(
        el(
          "p",
          "No locations yet. Add remote storage below, or ask your administrator to configure the folders available on this server.",
          "files-muted",
        ),
      );
  }
  async function packageList() {
    const result = await api("packages");
    const box = $("#package-list");
    box.replaceChildren();
    for (const p of result.items) {
      const card = el("article", undefined, "files-panel");
      card.append(
        el("h2", p.title),
        el("p", p.description),
        el(
          "p",
          p.expiry_days
            ? `${p.expiry_days}-day access per revision`
            : "No expiration",
          "files-muted",
        ),
        button("View revisions", () => packageDetail(p.id)),
      );
      box.append(card);
    }
    if (!result.items.length)
      box.append(
        el(
          "p",
          "Select files in the catalog, then create your first package.",
          "files-muted",
        ),
      );
  }
  async function packageDetail(id) {
    currentPackage = id;
    const p = await api("packages/" + id),
      box = $("#package-detail");
    box.replaceChildren(el("h2", p.title));
    box.append(
      button("New revision from current selection", async () => {
        await api(`packages/${id}/revisions`, {
          file_ids: [...selected],
          request_id: requestId(),
        });
        await packageDetail(id);
      }),
      button("Refresh history", () => packageDetail(id)),
    );
    for (const r of p.revisions) {
      const card = el("article", undefined, "files-revision");
      card.append(
        el("h3", `Revision ${r.number} · ${r.state}`),
        el(
          "p",
          `${r.files.length} files · Created ${date(r.created_at)} · Expires ${r.expires_at ? date(r.expires_at) : "—"}`,
          "files-muted",
        ),
      );
      const names = el("ul");
      r.files.forEach((f) => names.append(el("li", f.name)));
      card.append(names);
      if (r.error) card.append(el("p", "Publication error: " + r.error));
      if (["draft", "failed", "publishing"].includes(r.state))
        card.append(
          button(
            r.state !== "draft"
              ? "Retry publication"
              : "Publish to anyone with link",
            async () => {
              await api(`revisions/${r.id}/publish`, {});
              message(
                "Publication queued. Refresh history to follow progress.",
              );
            },
          ),
        );
      card.append(
        button("Use these files as selection", () => {
          selected.clear();
          r.file_ids.forEach((x) => selected.add(x));
          selection();
          message(
            "Revision files selected. Change the selection in Catalog, then create a new revision.",
          );
        }),
      );
      if (
        r.state === "published" &&
        (!r.expires_at || r.expires_at > Date.now() / 1000)
      ) {
        card.append(
          link("Open guest page", "/file-share/" + r.token),
          el("span", " · "),
          link("Open Drive folder", r.drive_url),
        );
        for (const target of ["drive", "page"])
          card.append(
            button(
              target === "drive" ? "Drive QR" : "Guest page QR",
              async () => {
                const q = await api(`revisions/${r.id}/qr?target=${target}`),
                  img = el("img");
                img.src = q.image;
                img.alt = target + " QR code";
                img.className = "files-qr";
                card.append(img, link("Open link", q.url));
              },
            ),
          );
      }
      box.append(card);
    }
    box.append(el("h3", "Audit history"));
    const audit = el("div", undefined, "files-audit");
    function appendEvents(events) {
      events.forEach((e) =>
        audit.append(
          el("p", `${date(e.at)} · ${e.kind} · ${JSON.stringify(e.data)}`),
        ),
      );
    }
    appendEvents(p.history);
    box.append(audit);
    if (p.history.length === 100) {
      let cursor = p.history.at(-1).id;
      const more = button("Older events", async () => {
        const older = await api(`packages/${id}?before=${cursor}`);
        appendEvents(older.history);
        cursor = older.history.at(-1)?.id || cursor;
        more.disabled = older.history.length < 100;
      });
      box.append(more);
    }
  }
  const ns = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    const n = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
  }
  let graphTransform = { x: 0, y: 0, scale: 1 },
    graphGroup;
  function transform() {
    graphGroup?.setAttribute(
      "transform",
      `translate(${graphTransform.x},${graphTransform.y}) scale(${graphTransform.scale})`,
    );
  }
  async function graph() {
    const data = await api("graph?" + filters()),
      root = $("#files-graph");
    root.replaceChildren();
    graphGroup = svg("g", {});
    root.append(graphGroup);
    graphTransform = { x: 0, y: 0, scale: 1 };
    const positions = {};
    for (const [kind, x] of [
      ["category", 120],
      ["file", 530],
      ["entity", 920],
    ]) {
      const nodes = data.nodes.filter((n) => n.kind === kind);
      nodes.forEach(
        (n, i) =>
          (positions[n.id] = {
            x,
            y: 40 + i * Math.max(24, 620 / Math.max(nodes.length, 1)),
          }),
      );
    }
    const height = Math.max(
      700,
      ...Object.values(positions).map((p) => p.y + 40),
    );
    root.setAttribute("viewBox", `0 0 1100 ${height}`);
    for (const e of data.edges) {
      const a = positions[e.source],
        b = positions[e.target];
      graphGroup.append(svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y }));
    }
    const accessible = $("#graph-accessible");
    accessible.replaceChildren();
    for (const n of data.nodes) {
      const p = positions[n.id],
        g = svg("g", {}),
        c = svg("circle", {
          cx: p.x,
          cy: p.y,
          r: n.kind === "file" ? 7 : 10,
          fill: { file: "#67e8f9", category: "#c4b5fd", entity: "#fbbf24" }[
            n.kind
          ],
        });
      const label = svg("text", { x: p.x + 14, y: p.y + 4 });
      label.textContent = (
        n.kind === "category" ? catName(n.label) : n.label
      ).slice(0, 36);
      g.append(c, label);
      if (n.file_id) {
        g.setAttribute("tabindex", "0");
        g.setAttribute("role", "button");
        g.setAttribute("aria-label", n.label);
        g.onclick = safe(() => detail(n.file_id));
        g.onkeydown = (e) => {
          if (e.key === "Enter") safe(() => detail(n.file_id))();
        };
        accessible.append(button(n.label, () => detail(n.file_id)));
      }
      graphGroup.append(g);
    }
    $("#graph-count").textContent =
      `${data.shown_files} of ${data.total_files} matching files · Violet categories / Cyan files / Gold entities`;
  }
  const canvas = $("#files-graph");
  let drag = null;
  canvas.onpointerdown = (e) => {
    if (e.target === canvas || e.target.tagName === "line") {
      drag = {
        x: e.clientX,
        y: e.clientY,
        baseX: graphTransform.x,
        baseY: graphTransform.y,
      };
      canvas.setPointerCapture(e.pointerId);
    }
  };
  canvas.onpointermove = (e) => {
    if (drag) {
      const ratio = canvas.viewBox.baseVal.width / canvas.clientWidth;
      graphTransform.x = drag.baseX + (e.clientX - drag.x) * ratio;
      graphTransform.y = drag.baseY + (e.clientY - drag.y) * ratio;
      transform();
    }
  };
  canvas.onpointerup = () => (drag = null);
  canvas.onwheel = (e) => {
    e.preventDefault();
    graphTransform.scale = Math.max(
      0.2,
      Math.min(8, graphTransform.scale * (e.deltaY < 0 ? 1.15 : 0.87)),
    );
    transform();
  };
  $("#graph-reset").onclick = () => {
    graphTransform = { x: 0, y: 0, scale: 1 };
    transform();
  };
  async function refresh() {
    await loadSources();
    sourceOptions();
    if (view === "catalog") await catalog();
    if (view === "sources") await sourceList();
    if (view === "packages") {
      await packageList();
      if (currentPackage) await packageDetail(currentPackage);
    }
    if (view === "graph") await graph();
  }
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => (b.onclick = safe(() => changeView(b.dataset.view))));
  $("#refresh-files").onclick = safe(refresh);
  $("#browse-files").onclick = safe(() => openPicker());
  $("#package-choose").onclick = safe(() => changeView("catalog"));
  $("#add-remote").onclick = () => {
    $("#source-settings").open = true;
    $("#source-form [name=name]").focus();
  };
  $("#source-form [name=kind]").onchange = sourceHelp;
  $("#reference-form [name=source_id]").onchange = referenceHelp;
  $("#close-folder").onclick = () => $("#folder-dialog").close();
  $("#folder-source").onchange = folderSafe(async () => {
    picked.clear(); pickerSelection(); folderPath = ""; folderOffset = 0; await loadFolder();
  });
  $("#folder-previous").onclick = folderSafe(async () => { folderOffset = Math.max(0, folderOffset - 100); await loadFolder(); });
  $("#folder-next").onclick = folderSafe(async () => { folderOffset += 100; await loadFolder(); });
  $("#add-picked").onclick = folderSafe(async () => {
    const sourceId = $("#folder-source").value;
    $("#add-picked").disabled = true;
    try {
      const result = await api(`sources/${sourceId}/select`, {paths: [...picked]});
      result.items.forEach((file) => selected.add(file.id));
      $("#folder-dialog").close();
      $("#filter-files").reset(); offset = 0;
      await changeView("catalog");
      message(`${result.items.length} files added and selected. Choose Create package from selection to share them.`);
    } finally { pickerSelection(); }
  });
  $("#filter-files").onsubmit = safe(async (e) => {
    e.preventDefault();
    offset = 0;
    await catalog();
  });
  $("#previous-page").onclick = safe(async () => {
    offset = Math.max(0, offset - pageSize);
    await catalog();
  });
  $("#next-page").onclick = safe(async () => {
    offset += pageSize;
    await catalog();
  });
  $("#selection-package").onclick = safe(() => changeView("packages"));
  $("#clear-selection").onclick = safe(async () => {
    selected.clear();
    await catalog();
  });
  $("#close-file").onclick = () => $("#file-dialog").close();
  $("#reference-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    await api("references", Object.fromEntries(new FormData(e.target)));
    await changeView("catalog");
    message("Reference registered. Availability will be checked on retrieval or discovery.");
  });
  $("#entity-search-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    const r = await fetch(
      "/api/hfl/entities?limit=20&q=" + encodeURIComponent(e.target.q.value),
    );
    if (!r.ok) throw Error("Entity search unavailable");
    const data = await r.json(),
      box = $("#entity-results");
    box.replaceChildren();
    for (const entity of data.entities)
      box.append(
        button(entity.label, () => {
          const input = $("#metadata-form [name=entities]");
          input.value = [...new Set([...list(input.value), entity.id])].join(
            ", ",
          );
        }),
      );
  });
  $("#source-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    const form = e.target,
      data = Object.fromEntries(new FormData(form));
    data.interval_hours = Number(data.interval_hours);
    data.categories = [...form.categories.selectedOptions].map((o) => o.value);
    data.tags = list(data.tags);
    await api("sources", data);
    message("Location added. Choose Scan now to index its files.");
    await refresh();
  });
  $("#metadata-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    const f = e.target;
    await api(
      "files/" + currentFile,
      {
        categories: [...f.categories.selectedOptions].map((o) => o.value),
        tags: list(f.tags.value),
        entities: list(f.entities.value),
      },
      "PATCH",
    );
    $("#file-dialog").close();
    message("Metadata saved.");
    await refresh();
  });
  $("#location-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    await api(
      `files/${currentFile}/locations`,
      Object.fromEntries(new FormData(e.target)),
    );
    await detail(currentFile);
    message("Location added.");
  });
  $("#package-form").onsubmit = safe(async (e) => {
    e.preventDefault();
    if (!selected.size) throw Error("Select files in the catalog first.");
    const data = Object.fromEntries(new FormData(e.target));
    data.expiry_days = Number(data.expiry_days);
    const p = await api("packages", data);
    await api(`packages/${p.id}/revisions`, {
      file_ids: [...selected],
      request_id: requestId(),
    });
    message("Draft created. Review the files before publishing.");
    await packageList();
    await packageDetail(p.id);
  });
  safe(async () => {
    try {
      categories = (await api("taxonomy")).categories;
    } catch (error) {
      message(error.message, true);
    }
    await loadSources();
    sourceHelp();
    sourceOptions();
    categoryOptions($("#filter-files [name=category]"), [], true);
    categoryOptions($("#source-form [name=categories]"));
    await catalog();
  })();
  let refreshing = false;
  setInterval(async () => {
    if (refreshing || document.hidden || !["catalog", "sources"].includes(view) || (!pendingScans.size && !sources.some((s) => s.state === "scanning"))) return;
    refreshing = true;
    try { await refresh(); } catch (error) { message(error.message, true); }
    finally { refreshing = false; }
  }, 5000);
})();
