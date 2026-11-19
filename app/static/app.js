/* AdRobot · Keitaro wrapper — фронт на jQuery */
window.App = (function ($) {
  "use strict";

  function esc(s) {
    return $("<div>").text(s == null ? "" : String(s)).html();
  }

  function alertBox(kind, html, timeout) {
    var $a = $('<div class="alert alert-' + kind + ' alert-dismissible fade show" role="alert">' + html +
      '<button type="button" class="btn-close" aria-label="Close"></button></div>');
    $a.find(".btn-close").on("click", function () { $a.remove(); });
    $("#alerts").append($a);
    if (timeout) setTimeout(function () { $a.remove(); }, timeout);
  }

  function errorText(xhr) {
    var j = xhr.responseJSON;
    if (j && j.detail) {
      if (typeof j.detail === "string") return j.detail;
      return j.detail.map(function (d) { return (d.loc || []).slice(-1)[0] + ": " + d.msg; }).join("; ");
    }
    return xhr.status ? ("HTTP " + xhr.status) : "сеть недоступна";
  }

  function api(method, url, data) {
    return $.ajax({
      method: method,
      url: url,
      contentType: "application/json",
      data: data === undefined ? undefined : JSON.stringify(data),
      dataType: "json"
    }).fail(function (xhr) { alertBox("danger", esc(errorText(xhr))); });
  }

  // select2 + jQuery 3.6+: поле поиска само не получает фокус
  $(document).on("select2:open", function () {
    var f = document.querySelector(".select2-container--open .select2-search__field");
    if (f) f.focus();
  });

  function offerSelect($el, placeholder) {
    $el.select2({
      theme: "bootstrap-5",
      width: "100%",
      placeholder: placeholder || "поиск оффера по имени или ID",
      allowClear: true,
      minimumInputLength: 0,
      ajax: {
        url: "/api/offers",
        delay: 250,
        data: function (p) { return { q: p.term || "" }; },
        processResults: function (items) {
          return { results: items.map(function (o) { return { id: o.id, text: "[" + o.id + "] " + o.name }; }) };
        },
        error: function (xhr) { if (xhr.statusText !== "abort") alertBox("danger", esc(errorText(xhr)), 6000); }
      }
    });
  }

  // ---------------- создаватор ----------------
  function initCreator() {
    offerSelect($("#offer"));

    var defaults = {};
    api("GET", "/api/lookups").done(function (d) {
      defaults = d.defaults;
      fill($("#domain"), d.domains, d.defaults.domain_id, "— домен —");
      fill($("#group"), d.groups, d.defaults.group_id, "— группа —");
      fill($("#source"), d.traffic_sources, d.defaults.traffic_source_id, "— источник —");
    });

    function resetForm() {
      // домен/группу/источник оставляем выбранными: обычно создают пачку кампаний подряд
      $("#name, #geo, #new_group_name").val("");
      $("#offer").val(null).trigger("change");
    }

    function fill($sel, items, def, empty) {
      $sel.empty().append('<option value="">' + empty + "</option>");
      items.forEach(function (i) {
        $sel.append($("<option>").val(i.id).text(i.name + " (#" + i.id + ")"));
      });
      if (def) $sel.val(String(def));
    }

    function intOrNull(v) { return v ? parseInt(v, 10) : null; }

    $("#create-form").on("submit", function (e) {
      e.preventDefault();
      var body = {
        name: $("#name").val(),
        geo: $("#geo").val(),
        offer_id: intOrNull($("#offer").val()),
        domain_id: intOrNull($("#domain").val()),
        group_id: intOrNull($("#group").val()),
        traffic_source_id: intOrNull($("#source").val()),
        new_group_name: $("#new_group_name").val() || null
      };
      if (!body.offer_id) { alertBox("warning", "Выберите оффер", 4000); return; }
      var $btn = $("#create-btn").prop("disabled", true).text("Создаю…");
      api("POST", "/api/campaigns", body).done(function (c) {
        $("#create-result").html(
          '<div class="alert alert-success">Кампания <b>' + esc(c.name) + "</b> создана в Keitaro (#" + c.id +
          ", alias <code>" + esc(c.alias || "") + "</code>, гео " + esc(c.geo.join(", ")) + "). " +
          '<a href="/campaigns/' + c.id + '">Открыть потоки →</a></div>');
        resetForm();
      }).always(function () { $btn.prop("disabled", false).text("Create"); });
    });
  }

  // ---------------- список кампаний ----------------
  function initCampaigns() {
    var all = [];
    api("GET", "/api/campaigns").done(function (items) { all = items; render(); })
      .fail(function () { $("#campaigns-body").html('<tr><td colspan="5" class="text-danger">Не удалось загрузить</td></tr>'); });

    $("#campaign-filter").on("input", render);

    function render() {
      var q = ($("#campaign-filter").val() || "").toLowerCase();
      var rows = all.filter(function (c) {
        return !q || String(c.id) === q || (c.name || "").toLowerCase().indexOf(q) >= 0;
      }).map(function (c) {
        return "<tr><td>" + c.id + "</td><td>" + esc(c.name) + "</td><td><code>" + esc(c.alias) + "</code></td><td>" +
          esc(c.state) + '</td><td class="text-end"><a class="btn btn-sm btn-outline-primary" href="/campaigns/' +
          c.id + '">Streams</a></td></tr>';
      });
      $("#campaigns-body").html(rows.join("") || '<tr><td colspan="5" class="text-muted">Нет кампаний</td></tr>');
    }
  }

  // ---------------- редактор потоков ----------------
  function initStreams() {
    var cid = $("#toolbar").data("campaign-id");
    var state = { streams: [] };

    function load() {
      api("GET", "/api/campaigns/" + cid).done(setCampaign);
    }

    function setCampaign(c) {
      state = c;
      if (c.name) $("#crumb-campaign").text(c.name);
      $("#fetched-at").text(c.fetched_at ? "Последний fetch из Keitaro: " + new Date(c.fetched_at + "Z").toLocaleString() :
        "Данные ещё не забирались из Keitaro — нажмите «Fetch streams from KT».");
      render();
    }

    function replaceStream(s) {
      state.streams = state.streams.map(function (x) { return x.id === s.id ? s : x; });
      render();
    }

    function render() {
      var showAll = $("#show-all").is(":checked");
      var $root = $("#streams").empty();
      if (!state.streams.length) {
        $root.html('<div class="text-muted">Потоков нет.</div>');
        return;
      }
      state.streams.forEach(function (s) { $root.append(renderStream(s, showAll)); });
      $root.find("select.add-offer").each(function () { offerSelect($(this), "добавить оффер…"); });
    }

    function renderStream(s, showAll) {
      var cls = s.dirty ? "stream-dirty" : "";
      var h = '<div class="card mb-4 shadow-sm stream ' + cls + '" data-stream="' + s.id + '">';
      h += '<div class="card-header d-flex flex-wrap align-items-center gap-2">' +
        "<span class=\"fw-semibold\">Stream: " + esc(s.name) + "</span>" +
        '<span class="text-muted small">(#' + s.position + ") stream_id " + s.keitaro_id + ", " + esc(s.type || "") +
        (s.schema ? ", " + esc(s.schema) : "") + "</span>";
      if (s.has_offers) {
        var bad = s.total_share !== 100;
        h += '<span class="badge ' + (bad ? "text-bg-danger" : "text-bg-secondary") + ' ms-auto">Σ ' + s.total_share + "%</span>";
      }
      h += "</div>";

      if (s.dirty) {
        h += '<div class="px-3 pt-3 d-flex gap-2 align-items-center">' +
          '<button class="btn btn-primary btn-sm push-btn">⭱ PUSH TO KT</button>' +
          '<button class="btn btn-light border btn-sm cancel-btn">✕ CANCEL</button>' +
          '<span class="small text-muted">Есть неопубликованные изменения</span></div>';
      }

      if (!s.has_offers) {
        h += '<div class="card-body text-muted small">Поток без офферов — обёртка его не разбирает.</div></div>';
        return h;
      }

      h += '<div class="table-responsive"><table class="table mb-0 align-middle"><thead><tr>' +
        '<th>Offer</th><th style="width:130px">Share</th><th class="text-end" style="width:160px">Actions</th></tr></thead><tbody>';
      s.offers.forEach(function (o) {
        if (!showAll && o.status === "removed" && !o.dirty) return;
        var removed = o.status === "removed";
        var rowCls = removed ? "offer-removed" : (o.dirty ? "offer-dirty" : "");
        h += '<tr class="' + rowCls + '" data-link="' + o.id + '">' +
          "<td>[" + o.offer_id + "] " + esc(o.name) +
          (o.is_new ? ' <span class="badge text-bg-warning">new</span>' : "") +
          (removed ? ' <span class="badge text-bg-secondary">removed</span>' : "") + "</td><td>";
        if (removed) {
          h += '<span class="share">0%</span>';
        } else {
          h += '<a href="#" class="share share-edit" title="Задать долю вручную (закрепит её)">' + o.share + "%</a> " +
            '<button class="btn btn-link btn-sm p-0 pin-btn ' + (o.pinned ? "pinned" : "") + '" title="' +
            (o.pinned ? "Открепить долю" : "Закрепить долю") + '">' + (o.pinned ? "📌" : "📍") + "</button>";
        }
        h += '</td><td class="text-end">' + (removed
          ? '<button class="btn btn-sm btn-outline-success bring-back-btn">↺ BRING BACK</button>'
          : '<button class="btn btn-sm btn-outline-danger remove-btn">🗑 REMOVE</button>') + "</td></tr>";
      });
      h += '</tbody></table></div>';
      h += '<div class="card-footer d-flex gap-2"><div class="flex-grow-1"><select class="add-offer"></select></div>' +
        '<button class="btn btn-outline-primary add-btn">+ ADD</button></div>';
      h += "</div>";
      return h;
    }

    function streamId(el) { return $(el).closest(".stream").data("stream"); }
    function linkId(el) { return $(el).closest("tr").data("link"); }

    $("#fetch-btn").on("click", function () {
      var dirty = state.streams.some(function (s) { return s.dirty; });
      if (dirty && !window.confirm("Есть неопубликованные изменения. Fetch заменит их тем, что сейчас в Keitaro. Продолжить?")) return;
      var $b = $(this).prop("disabled", true);
      api("POST", "/api/campaigns/" + cid + "/fetch").done(function (c) {
        setCampaign(c);
        alertBox("success", "Потоки получены из Keitaro", 2500);
      }).always(function () { $b.prop("disabled", false); });
    });

    $("#show-all").on("change", render);

    var $root = $("#streams");
    $root.on("click", ".add-btn", function () {
      var $card = $(this).closest(".stream");
      var offerId = $card.find("select.add-offer").val();
      if (!offerId) { alertBox("warning", "Выберите оффер", 3000); return; }
      var $b = $(this).prop("disabled", true);
      api("POST", "/api/streams/" + streamId(this) + "/offers", { offer_id: parseInt(offerId, 10) })
        .done(replaceStream).always(function () { $b.prop("disabled", false); });
    });
    $root.on("click", ".remove-btn", function () {
      api("POST", "/api/stream-offers/" + linkId(this) + "/remove").done(replaceStream);
    });
    $root.on("click", ".bring-back-btn", function () {
      api("POST", "/api/stream-offers/" + linkId(this) + "/bring-back").done(replaceStream);
    });
    $root.on("click", ".pin-btn", function () {
      var pinned = !$(this).hasClass("pinned");
      api("POST", "/api/stream-offers/" + linkId(this) + "/pin", { pinned: pinned }).done(replaceStream);
    });
    $root.on("click", ".share-edit", function (e) {
      e.preventDefault();
      var cur = parseInt($(this).text(), 10);
      var v = window.prompt("Доля оффера, % (0–100). Доля будет закреплена, остальные пересчитаются.", cur);
      if (v === null) return;
      var n = parseInt(v, 10);
      if (isNaN(n)) { alertBox("warning", "Нужно целое число", 3000); return; }
      api("POST", "/api/stream-offers/" + linkId(this) + "/share", { share: n }).done(replaceStream);
    });
    $root.on("click", ".cancel-btn", function () {
      api("POST", "/api/streams/" + streamId(this) + "/cancel").done(replaceStream);
    });
    $root.on("click", ".push-btn", function () {
      var $b = $(this).prop("disabled", true).text("Pushing…");
      api("POST", "/api/streams/" + streamId(this) + "/push").done(function (s) {
        replaceStream(s);
        alertBox("success", "Поток «" + esc(s.name) + "» опубликован в Keitaro", 2500);
      }).fail(load).always(function () { $b.prop("disabled", false).text("⭱ PUSH TO KT"); });
    });

    load();
  }

  return { initCreator: initCreator, initCampaigns: initCampaigns, initStreams: initStreams };
})(jQuery);
