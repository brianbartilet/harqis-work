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
    view = "catalog";
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
  }
  function filters() {
    return new URLSearchParams(new FormData($("#filter-files")));
  }
  async function changeView(name) {
    sources = (await api("sources")).items;
    sourceOptions();
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
    if (!result.items) {
      const tr = el("tr"),
        td = el("td", "No files found. Add a source and run its first scan.");
      td.colSpan = 6;
      tr.append(td);
      body.append(tr);
    }
    $("#file-count").textContent =
      `${total} files · ${offset + 1}–${Math.min(offset + pageSize, total)}`;
    $("#previous-page").disabled = offset === 0;
    $("#next-page").disabled = offset + pageSize >= total;
    selection();
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
    sources = (await api("sources")).items;
    const box = $("#source-list");
    box.replaceChildren();
    for (const s of sources) {
      const card = el("article", undefined, "files-panel");
      card.append(
        el("h2", s.name),
        el("p", `${s.kind} · ${s.enabled ? "enabled" : "paused"} · ${s.state}`),
        el("p", s.root, "files-path"),
        el(
          "p",
          `Every ${s.interval_hours} hours · Last scan ${date(s.last_scan)}${s.error ? " · " + s.error : ""}`,
          "files-muted",
        ),
      );
      card.append(
        button("Scan now", async () => {
          await api(`sources/${s.id}/scan`, {});
          message("Scan queued. Refresh to see progress.");
        }),
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
          await sourceList();
        }),
      );
      box.append(card);
    }
    if (!sources.length)
      box.append(
        el(
          "p",
          "Add your first base location to begin discovery.",
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
    message(
      "Reference registered. Availability will be checked on retrieval or discovery.",
    );
    await catalog();
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
    message("Source added. Run Scan now or wait for the recurring scan.");
    await sourceList();
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
    sources = (await api("sources")).items;
    sourceOptions();
    categoryOptions($("#filter-files [name=category]"), [], true);
    categoryOptions($("#source-form [name=categories]"));
    await catalog();
  })();
})();
