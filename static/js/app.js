(() => {
  "use strict";

  const C = {
    purple: "#37003c", green: "#00ff85", greenInk: "#00a85a", pink: "#e90052", cyan: "#04f5ff",
    violet: "#963cff", amber: "#ffbf00", muted: "#76637a", line: "#e6dbe8", page: "#f3eef4",
  };
  const FEATURE_LABELS = {
    goals: "Goals", assists: "Assists", minutes: "Minutes", matches: "Appearances",
    age: "Age", position: "Position", form: "Physical form",
  };
  const SLIDERS = [
    { key: "goals", label: "Goals per season", min: 0, max: 40, step: 0.5, limit: 60 },
    { key: "assists", label: "Assists per season", min: 0, max: 25, step: 0.5, limit: 40 },
    { key: "minutes", label: "Minutes per season", min: 0, max: 3420, step: 10, limit: 3420 },
    { key: "matches", label: "Appearances per season", min: 0, max: 38, step: 1, limit: 38 },
    { key: "age", label: "Age", min: 16, max: 40, step: 0.5, limit: 45, floor: 15 },
  ];
  const BLANK_PLAYER = {
    name: "", position: "Midfielder", form: "fit",
    goals: 5, assists: 3, minutes: 2000, matches: 28, age: 24, actual: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const state = {
    data: null, players: [], byId: new Map(), selected: null, charts: {},
    board: "under", lab: { ...BLANK_PLAYER }, labTimer: null, labSeq: 0,
  };

  // ------------------------------------------------------------------ formatting

  const fmtEur = (v) => (v == null ? "n/a" : `€${v >= 100 ? Math.round(v) : v.toFixed(1)}m`);
  const fmtPct = (p) => {
    const r = Math.round(p * 100);
    return `${r >= 0 ? "+" : "−"}${Math.abs(r)}%`;
  };
  const absPct = (p) => `${Math.abs(Math.round(p * 100))}%`;
  const fmtNum = (v, d = 1) => (Number.isInteger(v) ? String(v) : v.toFixed(d));
  const fold = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clubName = (team) => (team && (team.team_short || team.team)) || "";
  const initials = (name) => {
    const parts = (name || "?").split(/\s+/).filter(Boolean);
    return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  };

  function verdictFor(model, market) {
    if (market == null) return { cls: "none", label: "No market value", text: "Add one to data/market_values.csv, or enter it in the lab below." };
    const diff = (model - market) / market;
    if (Math.abs(diff) < 0.1) return { cls: "fair", label: "Fair value", text: `Model and market agree within ${absPct(diff)}.` };
    if (diff > 0) return { cls: "under", label: "Undervalued", text: `The stats are worth ${absPct(diff)} more than the market price.` };
    return { cls: "over", label: "Overpriced", text: `The market price is ${absPct(market / model - 1)} above what the stats justify.` };
  }

  function renderVerdict(el, model, market) {
    const v = verdictFor(model, market);
    el.innerHTML = `<span class="verdict-pill ${v.cls}">${v.label}</span><span>${esc(v.text)}</span>`;
  }

  // ------------------------------------------------------------------ api

  async function api(path, options) {
    const res = await fetch(path, options);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
    return body;
  }

  // ------------------------------------------------------------------ photos

  function photoCandidates(p) {
    const list = [];
    if (p.photo_url) list.push(p.photo_url);
    if (p.photo_code) state.data.photo_templates.forEach((t) => list.push(t.replace("{code}", p.photo_code)));
    return list;
  }

  function setPhoto(img, avatar, p) {
    const candidates = photoCandidates(p);
    const token = String(Math.random());
    img.dataset.token = token;
    avatar.textContent = initials(p.name);
    let i = 0;
    const next = () => {
      if (img.dataset.token !== token) return; // a newer player took over this <img>
      if (i >= candidates.length) { img.hidden = true; avatar.hidden = false; return; }
      img.hidden = false; avatar.hidden = true;
      img.src = candidates[i++];
    };
    img.onerror = next;
    img.alt = `${p.name} photo`;
    next();
  }

  function crestImg(team, cls = "") {
    return team && team.crest ? `<img class="${cls}" src="${esc(team.crest)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : "";
  }

  // ------------------------------------------------------------------ charts

  Chart.defaults.font.family = "'Barlow', system-ui, sans-serif";
  Chart.defaults.font.size = 13;
  Chart.defaults.color = C.muted;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.tooltip.backgroundColor = C.purple;
  Chart.defaults.plugins.tooltip.titleFont = { family: "'Barlow Condensed', sans-serif", weight: "700", size: 15 };
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;

  // Value labels at the end of horizontal bars.
  Chart.register({
    id: "barLabels",
    afterDatasetsDraw(chart, _args, opts) {
      if (!opts || !opts.format) return;
      const { ctx } = chart;
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        if (meta.type !== "bar" || meta.hidden) return;
        meta.data.forEach((bar, j) => {
          const v = ds.data[j];
          if (v == null) return;
          const negative = v < 0;
          ctx.save();
          ctx.font = "700 14px 'Barlow Condensed', sans-serif";
          ctx.fillStyle = opts.color || C.purple;
          ctx.textBaseline = "middle";
          ctx.textAlign = negative ? "right" : "left";
          ctx.fillText(opts.format(v, j), bar.x + (negative ? -6 : 6), bar.y);
          ctx.restore();
        });
      });
    },
  });

  function drawChart(key, canvasId, config) {
    if (state.charts[key]) state.charts[key].destroy();
    state.charts[key] = new Chart(document.getElementById(canvasId), config);
    return state.charts[key];
  }

  function comparisonChart(key, canvasId, model, market, dark = false) {
    const labels = ["Model", "Market"];
    const ink = dark ? "#fff" : C.purple;
    drawChart(key, canvasId, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: [model, market],
          backgroundColor: [C.green, dark ? C.cyan : C.purple],
          borderRadius: 6, barPercentage: 0.8, categoryPercentage: 0.9,
        }],
      },
      options: {
        indexAxis: "y", maintainAspectRatio: false, animation: { duration: 400 },
        layout: { padding: { right: 70 } },
        scales: {
          x: { beginAtZero: true, display: false, suggestedMax: Math.max(model || 0, market || 0) * 1.05 },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: ink, font: { weight: "700", size: 14, family: "'Barlow Condensed', sans-serif" } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => fmtEur(c.raw) } },
          barLabels: { format: (v) => fmtEur(v), color: ink },
        },
      },
    });
  }

  function driversChart(prediction) {
    const dropped = state.data.model.dropped_features || {};
    const items = prediction.contributions
      .filter((c) => !(c.feature in dropped))
      .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));
    // Symmetric axis with headroom so value labels fit on both sides of zero.
    const reach = Math.ceil((Math.max(5, ...items.map((c) => Math.abs(c.pct * 100))) * 1.4) / 10) * 10;
    drawChart("drivers", "chart-drivers", {
      type: "bar",
      data: {
        labels: items.map((c) => FEATURE_LABELS[c.feature] || c.feature),
        datasets: [{
          data: items.map((c) => Math.round(c.pct * 1000) / 10),
          backgroundColor: items.map((c) => (c.pct >= 0 ? C.green : C.pink)),
          borderRadius: 5, barPercentage: 0.75,
        }],
      },
      options: {
        indexAxis: "y", maintainAspectRatio: false,
        layout: { padding: { right: 8 } },
        scales: {
          x: { min: -reach, max: reach, grid: { color: C.line }, border: { display: false }, ticks: { callback: (v) => `${v > 0 ? "+" : ""}${Math.round(v)}%`, maxRotation: 0, maxTicksLimit: 7 } },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: C.purple, font: { weight: "700" } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${fmtPct(c.raw / 100)} vs the average player` } },
          barLabels: { format: (v) => fmtPct(v / 100) },
        },
      },
    });
    $("#drivers-caption").textContent =
      `How far each feature pushes the value above or below an average player in the data (${fmtEur(prediction.baseline_value_eur_m)}). The effects multiply together into the model value.`;
  }

  function seasonsChart(player) {
    const seasons = player.seasons || [];
    const estimated = seasons.some((s) => s.minutes_estimated);
    drawChart("seasons", "chart-seasons", {
      data: {
        labels: seasons.map((s) => s.label),
        datasets: [
          { type: "bar", label: "Goals", data: seasons.map((s) => s.goals), backgroundColor: C.purple, borderRadius: 4, yAxisID: "y", order: 2 },
          { type: "bar", label: "Assists", data: seasons.map((s) => s.assists), backgroundColor: C.pink, borderRadius: 4, yAxisID: "y", order: 2 },
          {
            type: "line", label: estimated ? "Minutes (some estimated)" : "Minutes", data: seasons.map((s) => s.minutes),
            borderColor: C.violet, backgroundColor: C.cyan, pointBackgroundColor: C.cyan, pointBorderColor: C.purple,
            pointRadius: 5, borderWidth: 3, tension: 0.3, yAxisID: "y1", order: 1,
            segment: estimated ? { borderDash: [6, 4] } : undefined,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { color: C.purple, font: { weight: "700" } } },
          y: { beginAtZero: true, grid: { color: C.line }, border: { display: false }, title: { display: true, text: "Goals / assists" }, ticks: { precision: 0 } },
          y1: { beginAtZero: true, position: "right", grid: { display: false }, border: { display: false }, title: { display: true, text: "Minutes" } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
    const teams = [...new Set(seasons.map((s) => s.team_short || s.team).filter(Boolean))];
    $("#seasons-caption").textContent =
      `${seasons.length} season${seasons.length === 1 ? "" : "s"} in the data${teams.length ? ` · ${teams.join(", ")}` : ""}` +
      (estimated ? " · dashed minutes are estimated from appearances" : "");
  }

  function scatterChart() {
    const pts = state.players.filter((p) => p.market_value_eur_m);
    if (!pts.length) return;
    const all = pts.flatMap((p) => [p.market_value_eur_m, p.predicted_value_eur_m]);
    const lo = Math.max(0.5, Math.min(...all) * 0.8);
    const hi = Math.max(...all) * 1.2;
    const sel = state.selected && state.selected.market_value_eur_m ? [state.selected] : [];
    const point = (p) => ({ x: p.market_value_eur_m, y: p.predicted_value_eur_m, id: p.id, name: p.name });
    drawChart("scatter", "chart-scatter", {
      type: "scatter",
      data: {
        datasets: [
          { label: "Selected", data: sel.map(point), backgroundColor: C.cyan, borderColor: C.purple, borderWidth: 3, pointRadius: 10, pointHoverRadius: 12, order: 0 },
          {
            label: "Players", data: pts.map(point), order: 1,
            backgroundColor: pts.map((p) => (p.predicted_value_eur_m >= p.market_value_eur_m ? "rgba(0,200,105,.75)" : "rgba(233,0,82,.7)")),
            pointRadius: 5, pointHoverRadius: 8,
          },
          { type: "line", label: "Model = market", data: [{ x: lo, y: lo }, { x: hi, y: hi }], borderColor: C.purple, borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0, order: 2 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { type: "logarithmic", min: lo, max: hi, title: { display: true, text: "Market value (€m, log scale)" }, grid: { color: C.line }, ticks: { callback: logTick, maxRotation: 0, autoSkip: false } },
          y: { type: "logarithmic", min: lo, max: hi, title: { display: true, text: "Model value (€m, log scale)" }, grid: { color: C.line }, ticks: { callback: logTick } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: (item) => item.datasetIndex !== 2,
            callbacks: {
              title: (items) => items[0].raw.name,
              label: (c) => [`Market ${fmtEur(c.raw.x)}`, `Model  ${fmtEur(c.raw.y)}`],
            },
          },
        },
        onClick: (_e, elements) => {
          const hit = elements.find((el) => el.datasetIndex !== 2);
          if (hit) selectPlayer(state.charts.scatter.data.datasets[hit.datasetIndex].data[hit.index].id, true);
        },
        onHover: (e, elements) => { e.native.target.style.cursor = elements.some((el) => el.datasetIndex !== 2) ? "pointer" : "default"; },
      },
    });
  }

  function logTick(value) {
    const nice = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
    return nice.includes(Number(value.toPrecision(2))) ? `€${value}m` : "";
  }

  // ------------------------------------------------------------------ top bar, search, picks

  function renderTopbar() {
    const { dataset, model } = state.data;
    const labels = dataset.season_labels || [];
    const range = labels.length > 1 ? `${labels[0]} – ${labels[labels.length - 1]}` : labels[0] || "";
    $("#topbar-meta").innerHTML = [
      range && `<span class="meta-chip">Seasons <b>${esc(range)}</b></span>`,
      `<span class="meta-chip">Players <b>${state.players.length}</b></span>`,
      `<span class="meta-chip">CV R² <b>${model.metrics.r2_log_cv.toFixed(2)}</b></span>`,
    ].filter(Boolean).join("");
  }

  function renderQuickPicks() {
    const top = state.players.filter((p) => p.market_value_eur_m).slice(0, 7);
    $("#quick-picks").innerHTML = top
      .map((p) => `<button class="pick" type="button" data-id="${p.id}">${esc(p.name)}</button>`)
      .join("");
    $("#quick-picks").addEventListener("click", (e) => {
      const btn = e.target.closest(".pick");
      if (btn) selectPlayer(Number(btn.dataset.id), true);
    });
  }

  function setupSearch() {
    const input = $("#search-input");
    const list = $("#search-results");
    const box = input.closest(".search");
    let results = [];
    let active = -1;
    input.disabled = false;

    const close = () => { list.hidden = true; box.setAttribute("aria-expanded", "false"); active = -1; };
    const highlight = () => {
      [...list.children].forEach((li, i) => li.setAttribute("aria-selected", i === active ? "true" : "false"));
      if (list.children[active]) list.children[active].scrollIntoView({ block: "nearest" });
    };
    const choose = (i) => {
      if (!results[i]) return;
      selectPlayer(results[i].id, true);
      input.value = "";
      close();
      input.blur();
    };

    input.addEventListener("input", () => {
      const q = fold(input.value.trim());
      if (!q) { close(); return; }
      results = state.players
        .filter((p) => fold(`${p.name} ${p.team.team || ""} ${p.team.team_short || ""}`).includes(q))
        .slice(0, 8);
      list.innerHTML = results.length
        ? results.map((p, i) => `
            <li role="option" id="sr-${i}" data-i="${i}" aria-selected="false">
              ${crestImg(p.team, "sr-crest")}
              <span class="sr-name">${esc(p.name)}</span>
              <span class="sr-meta">${esc(clubName(p.team))} · ${esc(p.position)} · ${fmtEur(p.market_value_eur_m)}</span>
            </li>`).join("")
        : `<li class="muted">No player matches “${esc(input.value.trim())}”. Try the lab below for anyone else.</li>`;
      list.hidden = false;
      box.setAttribute("aria-expanded", "true");
      active = results.length ? 0 : -1;
      highlight();
    });
    input.addEventListener("keydown", (e) => {
      if (list.hidden) return;
      if (e.key === "ArrowDown") { active = Math.min(active + 1, results.length - 1); highlight(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); highlight(); e.preventDefault(); }
      else if (e.key === "Enter") { choose(active); e.preventDefault(); }
      else if (e.key === "Escape") close();
    });
    list.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); choose(Number(li.dataset.i)); }
    });
    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  // ------------------------------------------------------------------ player view

  async function selectPlayer(id, scroll = false) {
    let player;
    try {
      player = await api(`/api/players/${id}`);
    } catch (err) {
      console.error(err);
      return;
    }
    state.selected = player;
    history.replaceState(null, "", `#player-${id}`);
    renderHero(player);
    renderStats(player);
    driversChart(player.prediction);
    seasonsChart(player);
    scatterChart();
    loadLabFrom(player);
    if (scroll) $("#hero").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderHero(p) {
    const words = p.name.split(/\s+/);
    $("#hero-first").textContent = words.length > 1 ? words.slice(0, -1).join(" ") : "";
    $("#hero-last").textContent = words[words.length - 1];
    $("#hero-number").textContent = p.shirt_number || "";
    $("#hero-club").textContent = p.team.team || "";
    const crest = $("#hero-crest");
    if (p.team.crest) { crest.src = p.team.crest; crest.hidden = false; crest.onerror = () => { crest.hidden = true; }; }
    else crest.hidden = true;
    setPhoto($("#hero-photo"), $("#hero-avatar"), p);

    const formTitle = {
      fpl: "From the Fantasy Premier League availability flag",
      override: "Set by hand in data/market_values.csv",
      availability: "Estimated from how many matches the player featured in last season",
    }[p.form_source] || "";
    $("#hero-chips").innerHTML = [
      `<span class="chip">${esc(p.position_detail && p.position_detail !== p.position ? `${p.position} · ${p.position_detail}` : p.position)}</span>`,
      p.age != null ? `<span class="chip">Age ${Math.floor(p.age)}</span>` : "",
      p.nationality ? `<span class="chip">${esc(p.nationality)}</span>` : "",
      `<span class="chip form-${esc(p.form)}" title="${esc(formTitle)}">${p.form === "injured" ? "✚ " : ""}${esc(p.form)}</span>`,
    ].join("");
    const news = (p.fpl && p.fpl.news) || "";
    $("#hero-news").textContent = news;
    $("#hero-news").hidden = !news;

    $("#value-model").textContent = fmtEur(p.predicted_value_eur_m);
    $("#value-market").textContent = fmtEur(p.market_value_eur_m);
    renderVerdict($("#verdict"), p.predicted_value_eur_m, p.market_value_eur_m);
    comparisonChart("compare", "chart-compare", p.predicted_value_eur_m, p.market_value_eur_m);
  }

  function renderStats(p) {
    const f = p.features;
    const per90 = f.minutes > 0 ? ((f.goals + f.assists) / f.minutes) * 90 : 0;
    const n = (p.seasons || []).length;
    const span = n > 1 ? `avg of ${n} seasons` : "1 season";
    const tiles = [
      [fmtNum(f.goals), "Goals", span],
      [fmtNum(f.assists), "Assists", span],
      [Math.round(f.minutes).toLocaleString(), "Minutes", p.minutes_estimated ? "partly estimated" : span],
      [fmtNum(f.matches), "Appearances", span],
      [per90.toFixed(2), "G+A per 90", "goal involvements"],
      [p.age != null ? fmtNum(p.age) : "–", "Age", p.date_of_birth ? `born ${p.date_of_birth}` : ""],
    ];
    $("#stat-strip").innerHTML = tiles.map(([v, label, note]) => `
      <div class="stat"><span class="stat-value">${esc(v)}</span><span class="stat-label">${esc(label)}</span><span class="stat-note">${esc(note)}</span></div>`).join("");
  }

  // ------------------------------------------------------------------ leaderboard

  function renderBoard() {
    const rows = state.players.filter((p) => p.market_value_eur_m);
    const sorted = {
      under: rows.slice().sort((a, b) => b.diff_pct - a.diff_pct),
      over: rows.slice().sort((a, b) => a.diff_pct - b.diff_pct),
      value: rows.slice().sort((a, b) => b.market_value_eur_m - a.market_value_eur_m),
    }[state.board].slice(0, 8);
    $("#board tbody").innerHTML = sorted.map((p, i) => `
      <tr data-id="${p.id}" tabindex="0">
        <td class="pos">${i + 1}</td>
        <td><div class="board-player">${crestImg(p.team) || `<span class="avatar small">${esc(initials(p.name))}</span>`}
          <span><span class="bp-name">${esc(p.name)}</span><span class="bp-club">${esc(clubName(p.team))} · ${esc(p.position)}</span></span></div></td>
        <td class="num">${fmtEur(p.market_value_eur_m)}</td>
        <td class="num">${fmtEur(p.predicted_value_eur_m)}</td>
        <td class="num ${p.diff_pct >= 0 ? "diff-up" : "diff-down"}">${fmtPct(p.diff_pct)}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="muted">No players with market values yet.</td></tr>`;
  }

  function setupBoard() {
    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
      state.board = tab.dataset.board;
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      renderBoard();
    }));
    const open = (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr && (e.type === "click" || e.key === "Enter")) selectPlayer(Number(tr.dataset.id), true);
    };
    $("#board tbody").addEventListener("click", open);
    $("#board tbody").addEventListener("keydown", open);
  }

  // ------------------------------------------------------------------ model card

  function renderModelCard() {
    const { model, dataset } = state.data;
    const m = model.metrics;
    $("#metrics").innerHTML = [
      [m.n_train, `players trained on (of ${m.n_players})`],
      [m.r2_log_cv.toFixed(2), `R² on unseen players (${m.folds}-fold CV)`],
      [fmtEur(m.mae_eur_m_cv), "average miss on unseen players"],
      [`${Math.round(m.median_abs_pct_error_cv * 100)}%`, "median miss on unseen players"],
    ].map(([v, l]) => `<div class="metric"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");

    const effects = model.per_unit_effects;
    const maxAbs = Math.max(...effects.filter((e) => !e.dropped).map((e) => Math.abs(e.pct)), 0.01);
    $("#effects tbody").innerHTML = effects.map((e) => {
      if (e.dropped) {
        return `<tr><td>${esc(e.unit)}</td><td class="bar-cell"><div class="effect-bar"><span class="mid"></span></div></td>
          <td class="num muted">not used</td></tr>`;
      }
      const w = (Math.abs(e.pct) / maxAbs) * 50;
      const style = e.pct >= 0 ? `left:50%;width:${w}%;background:${C.green}` : `left:${50 - w}%;width:${w}%;background:${C.pink}`;
      return `<tr><td>${esc(e.unit)}</td>
        <td class="bar-cell"><div class="effect-bar"><span class="mid"></span><i style="${style}"></i></div></td>
        <td class="num ${e.pct >= 0 ? "diff-up" : "diff-down"}">${fmtPct(e.pct)}</td></tr>`;
    }).join("");

    const src = dataset.sources || {};
    const counts = model.category_counts;
    const unseen = [
      ...Object.entries(counts.position).filter(([, n]) => !n).map(([k]) => k.toLowerCase() + "s"),
      ...Object.entries(counts.form).filter(([, n]) => !n).map(([k]) => `${k} players`),
    ];
    const notes = [
      `<b>Target:</b> the log of each player's market value, so every feature acts as a percentage. A plain linear fit in euros would happily predict negative prices for squad players.`,
      `<b>Features:</b> per-season averages of goals, assists, minutes and appearances over ${esc((dataset.season_labels || []).join(", "))}, plus age (with a squared term so value can peak${model.peak_age ? ` — the model puts the peak at <b>${model.peak_age}</b>` : ""}), position and physical form.`,
      `<b>Data:</b> football-data.org scorer tables${src.fpl ? `, with minutes, availability and photos for ${src.fpl_matched} players matched in the Fantasy Premier League API` : ". FPL enrichment was off, so minutes are estimated from appearances and form comes from availability"}.`,
      `<b>Scope:</b> football-data.org only lists players who scored, so attackers dominate and goalkeepers are rare. ${unseen.length ? `There are no ${esc(unseen.join(" or "))} with a market value in the training data, so those categories have no learned effect.` : ""}`,
      ...Object.entries(model.dropped_features || {}).map(([name, why]) =>
        `<b>${esc(FEATURE_LABELS[name] || name)} left out:</b> ${esc(why)}. Run the fetch without <code>--no-fpl</code> (and with FPL reachable) to bring it back.`),
      dataset.unmatched_market_values && dataset.unmatched_market_values.length
        ? `<b>Unmatched:</b> ${dataset.unmatched_market_values.length} rows in market_values.csv didn't match anyone in the fetched seasons and were left out.` : "",
      `<b>Market values</b> come from <code>data/market_values.csv</code>. They are rough reference figures; edit them to match your preferred source, then rerun <code>python -m predictor train</code>.`,
    ].filter(Boolean);
    $("#model-notes").innerHTML = `<h3 class="sub-title">Read this before quoting a number</h3><ul>${notes.map((n) => `<li>${n}</li>`).join("")}</ul>`;
  }

  // ------------------------------------------------------------------ lab

  function setupLab() {
    const { positions, forms } = state.data;
    const seg = (el, values, key) => {
      el.innerHTML = values.map((v) => `<button type="button" data-value="${esc(v)}" aria-pressed="false">${esc(v.charAt(0).toUpperCase() + v.slice(1))}</button>`).join("");
      el.addEventListener("click", (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        state.lab[key] = btn.dataset.value;
        syncLabControls();
        queueLabPrediction();
      });
    };
    seg($("#lab-position"), positions, "position");
    seg($("#lab-form-state"), forms, "form");

    const dropped = state.data.model.dropped_features || {};
    $("#lab-sliders").innerHTML = SLIDERS.map((s) => `
      <div class="slider-row">
        <label for="lab-${s.key}">${esc(s.label)}${dropped[s.key] ? " <em>(not used by this model)</em>" : ""}</label>
        <input type="range" id="lab-${s.key}-range" min="${s.min}" max="${s.max}" step="${s.step}" aria-label="${esc(s.label)}">
        <input type="number" id="lab-${s.key}" min="${s.floor ?? s.min}" max="${s.limit}" step="${s.step}" inputmode="decimal">
      </div>`).join("");
    SLIDERS.forEach((s) => {
      const range = $(`#lab-${s.key}-range`);
      const num = $(`#lab-${s.key}`);
      range.addEventListener("input", () => { state.lab[s.key] = Number(range.value); num.value = range.value; queueLabPrediction(); });
      num.addEventListener("input", () => {
        if (num.value === "" || Number.isNaN(Number(num.value))) return;
        state.lab[s.key] = Math.min(s.limit, Math.max(s.floor ?? s.min, Number(num.value)));
        range.value = state.lab[s.key];
        queueLabPrediction();
      });
      num.addEventListener("change", syncLabControls);
    });
    $("#lab-name").addEventListener("input", (e) => { state.lab.name = e.target.value; });
    $("#lab-actual").addEventListener("input", (e) => {
      const v = parseFloat(e.target.value);
      state.lab.actual = Number.isFinite(v) && v > 0 ? v : null;
      renderLabResult();
    });
    $("#lab-load").addEventListener("click", () => { if (state.selected) loadLabFrom(state.selected); });
    $("#lab-clear").addEventListener("click", () => { state.lab = { ...BLANK_PLAYER }; syncLabControls(); queueLabPrediction(); });
    $("#lab-form").addEventListener("submit", (e) => e.preventDefault());
  }

  function loadLabFrom(p) {
    const f = p.features;
    state.lab = {
      name: p.name, position: f.position, form: f.form,
      goals: f.goals, assists: f.assists, minutes: Math.round(f.minutes), matches: f.matches, age: f.age,
      actual: p.market_value_eur_m,
    };
    syncLabControls();
    queueLabPrediction(0);
  }

  function syncLabControls() {
    const lab = state.lab;
    $("#lab-name").value = lab.name || "";
    $("#lab-actual").value = lab.actual ?? "";
    SLIDERS.forEach((s) => {
      $(`#lab-${s.key}-range`).value = lab[s.key];
      $(`#lab-${s.key}`).value = Math.round(lab[s.key] * 100) / 100;
    });
    [["#lab-position", lab.position], ["#lab-form-state", lab.form]].forEach(([sel, value]) => {
      $(sel).querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.value === value ? "true" : "false"));
    });
  }

  function queueLabPrediction(delay = 150) {
    clearTimeout(state.labTimer);
    state.labTimer = setTimeout(runLabPrediction, delay);
  }

  async function runLabPrediction() {
    const seq = ++state.labSeq;
    const { name, actual, ...features } = state.lab;
    try {
      const result = await api("/api/predict", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(features),
      });
      if (seq !== state.labSeq) return; // a newer request is on its way
      state.labResult = result;
      renderLabResult();
    } catch (err) {
      if (seq !== state.labSeq) return;
      state.labResult = null;
      $("#lab-value").textContent = "–";
      $("#lab-warnings").innerHTML = `<li>${esc(err.message)}</li>`;
    }
  }

  function renderLabResult() {
    const r = state.labResult;
    if (!r) return;
    const value = r.predicted_value_eur_m;
    $("#lab-value").textContent = fmtEur(value);
    renderVerdict($("#lab-verdict"), value, state.lab.actual);
    comparisonChart("lab", "chart-lab", value, state.lab.actual, true);
    $("#lab-warnings").innerHTML = r.warnings.map((w) => `<li>${esc(w)}</li>`).join("");
  }

  // ------------------------------------------------------------------ boot

  function showSetup(info) {
    $("#setup").hidden = false;
    $(".search-band").hidden = true;
    $("#setup-message").textContent = `${info.message || "Nothing to show yet."} Three steps and you're in.`;
    $("#key-status").innerHTML = info.api_key_set
      ? `<span class="key-ok">✓ key detected</span>`
      : `<span class="key-missing">no key detected yet</span>`;
  }

  async function init() {
    let info;
    try {
      info = await api("/api/state");
    } catch (err) {
      showSetup({ message: `Couldn't reach the server (${err.message}).` });
      return;
    }
    if (!info.ready) { showSetup(info); return; }
    state.data = info;
    state.players = info.players;
    state.players.forEach((p) => state.byId.set(p.id, p));
    $("#dashboard").hidden = false;

    renderTopbar();
    renderQuickPicks();
    setupSearch();
    setupBoard();
    renderBoard();
    renderModelCard();
    setupLab();

    const fromHash = Number((location.hash.match(/^#player-(\d+)$/) || [])[1]);
    const first = state.byId.has(fromHash) ? fromHash : (state.players.find((p) => p.market_value_eur_m) || state.players[0]).id;
    await selectPlayer(first);
  }

  init();
})();
