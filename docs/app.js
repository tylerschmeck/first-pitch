/* First Pitch — app logic. No dependencies, no build step. */
(function () {
  "use strict";

  // ---------- tiny helpers ----------
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function store(key, val) {
    try {
      if (val === undefined) { var v = localStorage.getItem(key); return v ? JSON.parse(v) : null; }
      localStorage.setItem(key, JSON.stringify(val));
    } catch (e) { return null; }
  }
  function fmtMoney(n) {
    if (n == null || isNaN(n)) return "—";
    if (n >= 1e6) return "$" + (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
    if (n >= 1e3) return "$" + Math.round(n / 1e3) + "K";
    return "$" + Math.round(n);
  }
  function fmtInt(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }
  function daysAgo(iso) {
    if (!iso) return null;
    var d = new Date(iso + (iso.length === 10 ? "T12:00:00Z" : ""));
    return Math.max(0, Math.floor((Date.now() - d.getTime()) / 864e5));
  }
  function agoLabel(days) {
    if (days == null) return "";
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return days + "d ago";
    if (days < 75) return Math.round(days / 7) + "w ago";
    return Math.round(days / 30) + "mo ago";
  }
  function niceDate(iso) {
    if (!iso) return "";
    var d = new Date(iso + (iso.length === 10 ? "T12:00:00Z" : ""));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  // ---------- state ----------
  var DATA = null;
  var saved = new Set(store("fp_saved") || []);
  var hidden = new Set(store("fp_hidden") || []);
  var F = Object.assign({ q: "", groups: [], types: [], state: "", sort: "new", tab: "all" },
                        store("fp_filters") || {});
  F.tab = "all"; // always land on the full list

  // ---------- theme ----------
  var themeBtn = $("#themeToggle");
  var savedTheme = store("fp_theme");
  if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);
  themeBtn.addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store("fp_theme", next);
  });

  // ---------- load ----------
  fetch("data/jobs.json?t=" + Math.floor(Date.now() / 6e5))
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) { DATA = d; boot(); })
    .catch(function (e) {
      $("#summary").innerHTML = '<p class="empty-big">Couldn’t load the job list.</p>' +
        '<p class="sum-item">If you opened this file directly, serve it over http instead (or visit the hosted page). (' + esc(e.message) + ")</p>";
    });

  function boot() {
    var gen = new Date(DATA.generated_at);
    var hrs = (Date.now() - gen.getTime()) / 36e5;
    var upd = $("#updated");
    upd.innerHTML = '<span class="dot"></span>updated ' + esc(relHours(hrs));
    upd.title = "Last sweep: " + gen.toLocaleString() + " — boards are re-swept every 3 hours";
    if (hrs > 9) { upd.classList.add("stale"); upd.innerHTML += " — sweeps may be paused"; }

    $("#eadaYear").textContent = DATA.eada_year || "latest";
    $("#srcList").innerHTML = DATA.sources.map(function (s) {
      return s.ok ? esc(s.name) : "<s title='failed on the last sweep'>" + esc(s.name) + "</s>";
    }).join(" · ");

    buildStateSelect();
    restoreControls();
    wireControls();
    render();
  }

  function relHours(h) {
    if (h < 1) return "just now";
    if (h < 36) return Math.round(h) + "h ago";
    return Math.round(h / 24) + " days ago";
  }

  // ---------- controls ----------
  function buildStateSelect() {
    var counts = {};
    DATA.jobs.forEach(function (j) { if (j.state) counts[j.state] = (counts[j.state] || 0) + 1; });
    var opts = Object.keys(counts).sort().map(function (st) {
      return '<option value="' + st + '">' + st + " (" + counts[st] + ")</option>";
    });
    $("#stateSel").innerHTML = '<option value="">All states</option>' + opts.join("");
  }

  function restoreControls() {
    $("#q").value = F.q;
    $("#stateSel").value = F.state;
    if (!$("#stateSel").value) F.state = "";
    $("#sortSel").value = F.sort;
    $$("#divChips .chip").forEach(function (c) { c.classList.toggle("is-on", F.groups.indexOf(c.dataset.group) > -1); });
    $$("#typeChips .chip").forEach(function (c) { c.classList.toggle("is-on", F.types.indexOf(c.dataset.type) > -1); });
  }

  function persist() { store("fp_filters", { q: F.q, groups: F.groups, types: F.types, state: F.state, sort: F.sort }); }

  function wireControls() {
    var t;
    $("#q").addEventListener("input", function (e) {
      clearTimeout(t);
      t = setTimeout(function () { F.q = e.target.value.trim(); persist(); render(); }, 120);
    });
    $("#stateSel").addEventListener("change", function (e) { F.state = e.target.value; persist(); render(); });
    $("#sortSel").addEventListener("change", function (e) { F.sort = e.target.value; persist(); render(); });
    $$("#divChips .chip").forEach(function (c) {
      c.addEventListener("click", function () {
        toggleIn(F.groups, c.dataset.group); c.classList.toggle("is-on"); persist(); render();
      });
    });
    $$("#typeChips .chip").forEach(function (c) {
      c.addEventListener("click", function () {
        toggleIn(F.types, c.dataset.type); c.classList.toggle("is-on"); persist(); render();
      });
    });
    $$(".tabs .tab").forEach(function (tb) {
      tb.addEventListener("click", function () {
        F.tab = tb.dataset.tab;
        $$(".tabs .tab").forEach(function (x) {
          x.classList.toggle("is-active", x === tb);
          x.setAttribute("aria-selected", x === tb ? "true" : "false");
        });
        render();
      });
    });
    function clearAll() {
      F.q = ""; F.groups = []; F.types = []; F.state = "";
      restoreControls(); persist(); render();
    }
    $("#clearBtn").addEventListener("click", clearAll);
    $("#emptyClear").addEventListener("click", clearAll);
  }

  function toggleIn(arr, v) { var i = arr.indexOf(v); i > -1 ? arr.splice(i, 1) : arr.push(v); }

  // ---------- filtering ----------
  function visibleJobs() {
    var q = F.q.toLowerCase();
    return DATA.jobs.filter(function (j) {
      if (F.tab === "saved") return saved.has(j.id);
      if (F.tab === "hidden") return hidden.has(j.id);
      if (hidden.has(j.id)) return false;
      if (F.groups.length && F.groups.indexOf(j.group) === -1) return false;
      if (F.types.length && F.types.indexOf(j.type) === -1) return false;
      if (F.state && j.state !== F.state) return false;
      if (q) {
        var hay = (j.title + " " + j.school_name + " " + j.city + " " + j.state + " " +
                   j.division + " " + (j.school && j.school.conference || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    }).sort(cmp[F.sort] || cmp.new);
  }

  var cmp = {
    new: function (a, b) { return (b.posted || "").localeCompare(a.posted || ""); },
    old: function (a, b) { return (a.posted || "").localeCompare(b.posted || ""); },
    budget: function (a, b) {
      return (b.school && b.school.sb_expenses || 0) - (a.school && a.school.sb_expenses || 0);
    },
    school: function (a, b) { return a.school_name.localeCompare(b.school_name); }
  };

  // ---------- rendering ----------
  var openCards = new Set();

  function render() {
    var jobs = visibleJobs();
    renderSummary(jobs);
    $("#nAll").textContent = "(" + DATA.jobs.filter(function (j) { return !hidden.has(j.id); }).length + ")";
    $("#nSaved").textContent = "(" + saved.size + ")";
    $("#nHidden").textContent = hidden.size ? "(" + hidden.size + ")" : "";
    var anyFilter = F.q || F.groups.length || F.types.length || F.state;
    $("#clearBtn").hidden = !anyFilter;

    var list = $("#list");
    list.innerHTML = jobs.map(cardHTML).join("");
    $("#empty").hidden = jobs.length > 0;

    jobs.forEach(function (j) {
      var card = $("#card-" + j.id);
      if (openCards.has(j.id)) expand(card, j, true);
      $(".card-head", card).addEventListener("click", function () { toggle(card, j); });
    });
  }

  function renderSummary(jobs) {
    var heads = 0, newThisWeek = 0;
    jobs.forEach(function (j) {
      if (j.type === "head") heads++;
      var d = daysAgo(j.posted); if (d != null && d <= 7) newThisWeek++;
    });
    var label = F.tab === "saved" ? "saved job" : F.tab === "hidden" ? "hidden job" : "open position";
    $("#summary").innerHTML =
      '<span class="sum-big">' + jobs.length + '<small>' + esc(label + (jobs.length === 1 ? "" : "s")) + "</small></span>" +
      (F.tab === "all" ? '<span class="sum-item"><b>' + heads + "</b> head coach</span>" +
        '<span class="sum-item"><b>' + (jobs.length - heads) + "</b> assistant &amp; other</span>" +
        (newThisWeek ? '<span class="sum-new">' + newThisWeek + " new this week</span>" : "") : "");
  }

  function divClass(group) {
    return { d1: "div-d1", d2: "div-d2", d3: "div-d3", naia: "div-naia", juco: "div-juco" }[group] || "div-other";
  }

  function cardHTML(j) {
    var days = daysAgo(j.posted);
    var isNew = days != null && days <= 5;
    var loc = [j.city, j.state].filter(Boolean).join(", ");
    var conf = j.school && j.school.conference;
    return '' +
      '<article class="card" id="card-' + j.id + '">' +
        '<button class="card-head" aria-expanded="false" aria-controls="body-' + j.id + '">' +
          '<div class="card-title">' + esc(j.title) +
            (isNew ? '<span class="badge-new">NEW</span>' : "") + "</div>" +
          '<div class="card-right">' +
            '<span class="posted">' + (j.posted_is_estimate ? "listed " : "posted ") + "<b>" +
              esc(agoLabel(days)) + "</b></span>" +
            '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg>' +
          "</div>" +
          '<div class="card-sub">' +
            '<span class="school-strong">' + esc(j.school_name || "Unknown school") + "</span>" +
            (loc ? '<span class="sep">·</span><span>' + esc(loc) + "</span>" : "") +
            '<span class="div-pill ' + divClass(j.group) + '">' + esc(j.division) + "</span>" +
            (conf ? '<span><span class="sep">· </span>' + esc(conf) + "</span>" : "") +
          "</div>" +
        "</button>" +
        '<div class="card-body" id="body-' + j.id + '" role="region"></div>' +
      "</article>";
  }

  function toggle(card, j) {
    if (card.classList.contains("is-open")) {
      card.classList.remove("is-open");
      $(".card-head", card).setAttribute("aria-expanded", "false");
      openCards.delete(j.id);
    } else {
      expand(card, j, false);
    }
  }

  function expand(card, j, instant) {
    var body = $(".card-body", card);
    if (!body.dataset.built) { body.innerHTML = bodyHTML(j); body.dataset.built = "1"; wireBody(body, j); }
    card.classList.add("is-open");
    $(".card-head", card).setAttribute("aria-expanded", "true");
    openCards.add(j.id);
  }

  function staffLine(s) {
    function part(ft, pt, word) {
      var bits = [];
      if (ft) bits.push(ft + " FT");
      if (pt) bits.push(pt + " PT");
      return bits.length ? bits.join(" + ") + " " + word : "no " + word;
    }
    return part(s.sb_head_ft, s.sb_head_pt, "head") + " · " + part(s.sb_asst_ft, s.sb_asst_pt, "asst");
  }

  function bodyHTML(j) {
    var s = j.school;
    var metaBits = [];
    if (j.salary) metaBits.push('<span class="salary-flag">' + esc(j.salary) + "</span>");
    metaBits.push("Posted <b>" + esc(niceDate(j.posted)) + "</b>" + (j.posted_is_estimate ? " <small>(first seen by this tracker)</small>" : ""));
    if (j.deadline) metaBits.push("Deadline: <b>" + esc(j.deadline) + "</b>");
    if (j.contact) metaBits.push("Contact: <b>" + esc(j.contact) + "</b>");

    var left;
    if (s) {
      var aid = s.student_aid_women;
      var yr = DATA.eada_year || "the latest survey";
      left =
        '<p class="sect-label">Program snapshot ' + srcTag() + "</p>" +
        '<dl class="stats">' +
          stat("Division", esc(s.division) + (s.conference ? ' <small>· ' + esc(s.conference) + "</small>" : ""),
            "The school's division as listed in its federal athletics filing. The conference comes from the NCAA's official member directory.") +
          stat("School", fmtInt(s.enrollment) + ' <small>students · ' + esc(shortSector(s.sector)) + "</small>",
            "Total enrollment and public/private status from the U.S. Dept. of Education (" + yr + "). Tap “School's federal profile” below to see the full record.") +
          stat("Softball budget", fmtMoney(s.sb_expenses) + ' <small>' + esc(yr) + "</small>",
            "Everything the school reported spending on its softball program in " + yr + " — coaching pay, travel, equipment, facilities, and scholarships where they apply. Schools file this themselves with the U.S. Dept. of Education under federal law (the EADA). It's dependable for comparing how big or well-funded programs are, but it's a self-reported total, not audited to the dollar.") +
          stat("Roster size", s.sb_players ? s.sb_players + ' <small>players</small>' : "—",
            "Softball players the school reported carrying in " + yr + " (from the same federal filing).") +
          stat("Avg HC salary", fmtMoney(s.hc_salary_women) + ' <small>women’s teams</small>',
            "The average pay across ALL of this school's women's-team head coaches — basketball, soccer, softball, and the rest — not softball alone. The federal survey doesn't split salary out by sport, so read this as roughly what a women's head coach earns here (" + yr + ", full-time-equivalent).") +
          stat("Avg asst salary", fmtMoney(s.ac_salary_women) + ' <small>women’s teams</small>',
            "Average pay across all of this school's women's-team assistant coaches (not softball alone) — same federal source and same caveat as head-coach pay (" + yr + ").") +
          stat("Coaching staff", esc(staffLine(s)),
            "Softball coaches the school reported, split into full-time and part-time (" + yr + "). A mostly part-time staff often points to a smaller-budget program.") +
          (s.group === "d3"
            ? stat("Athletic aid", '<small>none — D3 has no athletic scholarships</small>',
                "NCAA Division III schools don't give athletic scholarships by rule. Players get need- and merit-based aid like any other student.")
            : stat("Athletic aid (women)", fmtMoney(aid) + (aid ? ' <small>per year</small>' : ""),
                "Total athletic scholarship money awarded to women across every sport (not softball alone), " + yr + ". How much softball gets depends on how the school divides it up.")) +
        "</dl>";
    } else {
      left =
        '<p class="sect-label">Program snapshot</p>' +
        '<div class="no-data">This school has <b>no softball program</b> in the latest federal athletics survey — usually a ' +
        "<b>brand-new program</b> (a build-it-yourself opportunity) or a non-college employer. The “Program news” link " +
        "below is the fastest way to check what's going on.</div>";
    }

    var right = '<p class="sect-label">The situation</p>' +
      '<div class="meta-line">' + metaBits.map(function (b) { return "<span>" + b + "</span>"; }).join("") + "</div>" +
      (s ? sparkHTML(j) : "") +
      (j.snippet ? '<p class="snippet">' + esc(j.snippet) +
        ' <span class="snippet-src">— from the job posting</span></p>' : "");

    var links = j.links.slice();
    var direct = links.filter(function (l) { return l.source === "NFCA"; })[0];
    var primary = direct || links[0];
    var rest = links.filter(function (l) { return l !== primary; });

    var newsQ = encodeURIComponent('"' + j.school_name + '" softball');
    var actions =
      '<div class="actions">' +
        '<a class="btn btn-primary" href="' + esc(primary.url) + '" target="_blank" rel="noopener">Apply' +
          (links.length > 1 ? " <small>(via " + esc(primary.source) + ")</small>" : "") + ' <span class="ext">↗</span></a>' +
        rest.map(function (l) {
          return '<a class="btn" href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.source) + ' <span class="ext">↗</span></a>';
        }).join("") +
        '<a class="btn btn-ghost" href="https://news.google.com/search?q=' + newsQ + '" target="_blank" rel="noopener">Program news <span class="ext">↗</span></a>' +
        (s && s.ath_url ? '<a class="btn btn-ghost" href="' + esc(s.ath_url) + '" target="_blank" rel="noopener">Team site <span class="ext">↗</span></a>' : "") +
        '<span class="spacer"></span>' +
        '<button class="btn btn-ghost btn-star" type="button">' + (saved.has(j.id) ? "★ Saved" : "☆ Save") + "</button>" +
        '<button class="btn btn-ghost btn-hide" type="button">' + (hidden.has(j.id) ? "Restore" : "Hide") + "</button>" +
      "</div>";

    var sources = "";
    if (s) {
      var yr2 = DATA.eada_year || "latest";
      var navUrl = j.unitid ? "https://nces.ed.gov/collegenavigator/?id=" + encodeURIComponent(j.unitid) : "";
      sources =
        '<div class="sources">' +
          '<span class="sources-label">Where these numbers come from</span>' +
          "<p>The program figures above are from the <b>EADA</b> — the Equity in Athletics Disclosure Act survey " +
          "that every college offering sports files with the U.S. Department of Education each year (this is the <b>" + esc(yr2) + "</b> filing). " +
          "Schools report the data themselves, so use it to compare programs' size and direction — not as exact, audited dollars. " +
          "Salaries and aid are school-wide women's-sports figures, not softball-only. Hover the ⓘ on any number for the specifics.</p>" +
          '<div class="sources-links">' +
            (navUrl ? '<a href="' + esc(navUrl) + '" target="_blank" rel="noopener">School\'s federal profile <span class="ext">↗</span></a>' : "") +
            '<a href="https://ope.ed.gov/athletics/#/search" target="_blank" rel="noopener">EADA athletics database <span class="ext">↗</span></a>' +
          "</div>" +
        "</div>";
    }

    return '<div class="body-grid"><div>' + left + "</div><div>" + right + "</div></div>" + sources + actions;
  }

  // A small "source" tag shown next to a section heading.
  function srcTag() {
    return '<button type="button" class="src-tag info" data-tip="' +
      esc("These figures come from the U.S. Dept. of Education's EADA athletics survey — the same federal filing every college submits. Details and a link to the source are at the bottom of this card.") +
      '" aria-label="Source: federal EADA athletics survey. Details at the bottom of this card.">federal data</button>';
  }

  function stat(label, val, tip) {
    var info = tip
      ? ' <button type="button" class="info" data-tip="' + esc(tip) +
        '" aria-label="' + esc("How this is measured: " + tip) + '">i</button>'
      : "";
    return '<div class="stat"><dt>' + esc(label) + info + "</dt><dd>" + (val || "—") + "</dd></div>";
  }

  function shortSector(sec) {
    if (!sec) return "";
    return sec.indexOf("Public") === 0 ? "public" : "private";
  }

  // ---------- sparkline ----------
  function sparkHTML(j) {
    var s = j.school;
    var ys = s.trend_years || [], ex = s.trend_exp || [];
    var pts = [];
    for (var i = 0; i < ys.length; i++) if (ex[i] != null) pts.push([ys[i], ex[i]]);
    if (pts.length < 3) return "";
    var first = pts[0][1], last = pts[pts.length - 1][1];
    var pct = first ? Math.round((last - first) / first * 100) : 0;
    var cls = pct > 3 ? "up" : pct < -3 ? "down" : "flat";
    var arrow = pct > 3 ? "▲" : pct < -3 ? "▼" : "→";
    var W = 320, H = 54, PX = 6, PT = 8, PB = 6;
    var min = Math.min.apply(null, pts.map(function (p) { return p[1]; }));
    var max = Math.max.apply(null, pts.map(function (p) { return p[1]; }));
    if (max === min) max = min + 1;
    var x = function (yr) { return PX + (yr - pts[0][0]) / (pts[pts.length - 1][0] - pts[0][0]) * (W - 2 * PX); };
    var y = function (v) { return PT + (1 - (v - min) / (max - min)) * (H - PT - PB); };
    var line = pts.map(function (p, i) { return (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1); }).join(" ");
    var area = line + " L" + x(pts[pts.length - 1][0]).toFixed(1) + " " + (H - 1) + " L" + x(pts[0][0]).toFixed(1) + " " + (H - 1) + " Z";
    var endX = x(pts[pts.length - 1][0]).toFixed(1), endY = y(last).toFixed(1);
    return '' +
      '<div class="spark-block">' +
        '<div class="spark-head"><span class="spark-title">Softball budget, ' + pts[0][0] + "–" + String(pts[pts.length - 1][0]).slice(2) +
          ' <button type="button" class="info" data-tip="' +
            esc("Six years of the school's reported softball spending, pulled from its federal EADA filings " + pts[0][0] + "–" + pts[pts.length - 1][0] + ". A steady climb signals a program the school is investing in; a drop can signal budget cuts. Hover any point for that year's figure.") +
            '" aria-label="How this trend is measured">i</button></span>' +
          '<span class="delta ' + cls + '">' + arrow + " " + Math.abs(pct) + "% <small>over " + (pts[pts.length - 1][0] - pts[0][0]) + " yrs</small></span></div>" +
        '<svg class="sparkline" viewBox="0 0 ' + W + " " + H + '" data-pts="' + esc(JSON.stringify(pts)) + '" preserveAspectRatio="none" role="img" aria-label="Budget trend ' +
           pts.map(function (p) { return p[0] + ": " + fmtMoney(p[1]); }).join(", ") + '">' +
          '<line class="base" x1="' + PX + '" y1="' + (H - 1) + '" x2="' + (W - PX) + '" y2="' + (H - 1) + '"/>' +
          '<path class="fill" d="' + area + '"/>' +
          '<path class="line" d="' + line + '"/>' +
          '<circle class="dot-end" cx="' + endX + '" cy="' + endY + '" r="3"/>' +
          '<circle class="hover-dot" r="4" opacity="0"/>' +
        "</svg>" +
        '<div class="spark-ends"><span>' + pts[0][0] + " · " + fmtMoney(first) + "</span><span>" + pts[pts.length - 1][0] + " · <b>" + fmtMoney(last) + "</b></span></div>" +
        (rosterLine(s) || "") +
      "</div>";
  }

  function rosterLine(s) {
    var ys = s.trend_years || [], pl = s.trend_players || [];
    var pts = [];
    for (var i = 0; i < ys.length; i++) if (pl[i] != null) pts.push([ys[i], pl[i]]);
    if (pts.length < 2) return "";
    var a = pts[0], b = pts[pts.length - 1];
    return '<p class="fine">Roster: ' + a[1] + " players (" + a[0] + ") → <b>" + b[1] + "</b> (" + b[0] + ")</p>";
  }

  var tip = $("#tip");
  function wireBody(body, j) {
    $(".btn-star", body).addEventListener("click", function () {
      saved.has(j.id) ? saved.delete(j.id) : saved.add(j.id);
      store("fp_saved", Array.from(saved));
      this.textContent = saved.has(j.id) ? "★ Saved" : "☆ Save";
      this.classList.toggle("is-saved", saved.has(j.id));
      $("#nSaved").textContent = "(" + saved.size + ")";
    });
    $(".btn-hide", body).addEventListener("click", function () {
      hidden.has(j.id) ? hidden.delete(j.id) : hidden.add(j.id);
      store("fp_hidden", Array.from(hidden));
      openCards.delete(j.id);
      render();
    });
    var svg = $(".sparkline", body);
    if (svg) {
      var pts = JSON.parse(svg.dataset.pts);
      var dot = $(".hover-dot", svg);
      svg.addEventListener("mousemove", function (ev) {
        var r = svg.getBoundingClientRect();
        var fx = (ev.clientX - r.left) / r.width;
        var i = Math.round(fx * (pts.length - 1));
        i = Math.max(0, Math.min(pts.length - 1, i));
        var W = 320, H = 54, PX = 6, PT = 8, PB = 6;
        var min = Math.min.apply(null, pts.map(function (p) { return p[1]; }));
        var max = Math.max.apply(null, pts.map(function (p) { return p[1]; }));
        if (max === min) max = min + 1;
        var cx = PX + (pts[i][0] - pts[0][0]) / (pts[pts.length - 1][0] - pts[0][0]) * (W - 2 * PX);
        var cy = PT + (1 - (pts[i][1] - min) / (max - min)) * (H - PT - PB);
        dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("opacity", "1");
        tip.hidden = false;
        tip.textContent = pts[i][0] + " · " + fmtMoney(pts[i][1]);
        tip.style.left = (r.left + cx / W * r.width) + "px";
        tip.style.top = (r.top + cy / H * r.height) + "px";
      });
      svg.addEventListener("mouseleave", function () { dot.setAttribute("opacity", "0"); tip.hidden = true; });
    }
  }

  // ---------- info tooltips (source & accuracy notes) ----------
  // One popover, shown on hover, keyboard focus, or tap of any .info button.
  var infotip = $("#infotip");
  var infoAnchor = null;

  function showInfo(btn) {
    var text = btn.getAttribute("data-tip");
    if (!text) return;
    infoAnchor = btn;
    infotip.textContent = text;
    infotip.hidden = false;
    infotip.classList.remove("below");
    var r = btn.getBoundingClientRect();
    // measure, then place centered above the icon (or below if no room)
    var tw = infotip.offsetWidth, th = infotip.offsetHeight;
    var margin = 8;
    var cx = r.left + r.width / 2;
    var left = Math.max(margin, Math.min(cx, window.innerWidth - margin - tw / 2) );
    // clamp so the box stays fully on-screen
    left = Math.max(margin + tw / 2, Math.min(left, window.innerWidth - margin - tw / 2));
    var below = r.top - th - 10 < 4;
    infotip.classList.toggle("below", below);
    infotip.style.left = left + "px";
    infotip.style.top = (below ? r.bottom + 10 : r.top - 10) + "px";
    // point the arrow at the icon even when the box is clamped sideways
    var arrowX = cx - (left - tw / 2);
    arrowX = Math.max(12, Math.min(tw - 12, arrowX));
    infotip.style.setProperty("--arrow-x", arrowX + "px");
    btn.setAttribute("aria-expanded", "true");
  }
  function hideInfo() {
    if (!infoAnchor) return;
    infoAnchor.removeAttribute("aria-expanded");
    infoAnchor = null;
    infotip.hidden = true;
  }

  document.addEventListener("mouseover", function (e) {
    var btn = e.target.closest && e.target.closest(".info");
    if (btn) showInfo(btn);
  });
  document.addEventListener("mouseout", function (e) {
    var btn = e.target.closest && e.target.closest(".info");
    if (btn && btn === infoAnchor && !btn.contains(e.relatedTarget)) hideInfo();
  });
  document.addEventListener("focusin", function (e) {
    var btn = e.target.closest && e.target.closest(".info");
    if (btn) showInfo(btn);
  });
  document.addEventListener("focusout", function (e) {
    var btn = e.target.closest && e.target.closest(".info");
    if (btn && btn === infoAnchor) hideInfo();
  });
  // tap: toggle (mobile has no hover); stop the card from reacting
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".info");
    if (btn) {
      e.preventDefault(); e.stopPropagation();
      infoAnchor === btn ? hideInfo() : showInfo(btn);
    } else if (infoAnchor) {
      hideInfo();
    }
  });
  window.addEventListener("scroll", function () { if (infoAnchor) hideInfo(); }, true);
  window.addEventListener("resize", hideInfo);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hideInfo(); });
})();
