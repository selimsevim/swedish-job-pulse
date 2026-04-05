const SAMPLE_META = {
      last_updated: "2026-04-07T06:00:00Z",
      weeks_tracked: 12,
      date_range: { from: "2026-01-13", to: "2026-04-07" }
    };

    const SAMPLE_LIVE = {
      week: "2026-W15",
      date: "2026-04-07",
      total_ads: 42150,
      total_positions: 78420,
      remote_ads: 4820,
      entry_level_ads: 5620,
      trainee_ads: 342,
      larling_ads: 58,
      remote_by_field: [
        { term: "Data/IT", count: 1380, concept_id: "apaJ_2ja_LuF" },
        { term: "Administration, ekonomi, juridik", count: 740, concept_id: "X82t_awd_Qyc" },
        { term: "Försäljning, inköp, marknadsföring", count: 510, concept_id: "RPTn_bxG_ExZ" },
        { term: "Hälso- och sjukvård", count: 860, concept_id: "NYW6_mP6_vwf" }
      ],
      entry_by_field: [
        { term: "Hälso- och sjukvård", count: 1840, concept_id: "NYW6_mP6_vwf" },
        { term: "Pedagogik", count: 940, concept_id: "MVqp_eS8_kDZ" },
        { term: "Data/IT", count: 610, concept_id: "apaJ_2ja_LuF" }
      ],
      by_occupation_field: [
        { term: "Hälso- och sjukvård", count: 12500, concept_id: "NYW6_mP6_vwf" },
        { term: "Pedagogik", count: 8400, concept_id: "MVqp_eS8_kDZ" },
        { term: "Data/IT", count: 3200, concept_id: "apaJ_2ja_LuF" },
        { term: "Data/IT", count: 1800, concept_id: "apaJ_2ja_LuF" },
        { term: "Bygg och anläggning", count: 4200, concept_id: "j7Cq_ZJe_GkT" },
        { term: "Försäljning, inköp, marknadsföring", count: 3900, concept_id: "RPTn_bxG_ExZ" },
        { term: "Administration, ekonomi, juridik", count: 3100, concept_id: "X82t_awd_Qyc" },
        { term: "Industriell tillverkning", count: 2800, concept_id: "wTEr_CBC_bqh" },
        { term: "Transport, distribution, lager", count: 2200, concept_id: "ASGV_zcE_bWf" }
      ],
      by_region: [
        { term: "Stockholms län", count: 14200, concept_id: "CifL_Rzy_Mku" },
        { term: "Västra Götalands län", count: 8900, concept_id: "zdoY_6u5_Krt" },
        { term: "Skåne län", count: 7100, concept_id: "CaRE_1nn_cSU" },
        { term: "Östergötlands län", count: 2400, concept_id: "oLT3_Q9p_3nn" },
        { term: "Uppsala län", count: 2100, concept_id: "zBon_eET_fFU" }
      ]
    };

    const SAMPLE_HISTORY = Array.from({ length: 12 }, (_, index) => ({
      week: `2026-W${String(index + 4).padStart(2, "0")}`,
      date: `2026-03-${String(index + 1).padStart(2, "0")}`,
      total_ads: Math.round(38000 + (index * 400) + (Math.random() * 500)),
      total_positions: Math.round(70000 + (index * 800) + (Math.random() * 1000)),
      remote_ads: Math.round(4000 + (index * 80)),
      entry_level_ads: Math.round(4800 + (index * 70))
    }));

    const OPTIONAL_SECTION_CONFIG = [
      {
        key: "occupationDecay",
        path: "data/occupation_decay.json",
        updatedElementId: "occupation-decay-updated",
        bodyElementId: "occupation-decay-body",
        renderer: renderOccupationDecaySection
      },
      {
        key: "skillVelocity",
        path: "data/skill_velocity.json",
        updatedElementId: "skill-velocity-updated",
        bodyElementId: "skill-velocity-body",
        renderer: renderSkillVelocitySection
      },
      {
        key: "demandGap",
        path: "data/demand_gap.json",
        updatedElementId: "demand-gap-updated",
        bodyElementId: "demand-gap-body",
        renderer: renderDemandGapSection
      },
      {
        key: "adLifespan",
        path: "data/ad_lifespan.json",
        updatedElementId: "ad-lifespan-updated",
        bodyElementId: "ad-lifespan-body",
        renderer: renderAdLifespanSection
      },
      {
        key: "regionalSplit",
        path: "data/regional_split.json",
        updatedElementId: "regional-split-updated",
        bodyElementId: "regional-split-body",
        renderer: renderRegionalSplitSection
      }
    ];

    const charts = {};
    const MIN_SKILL_CURRENT_COUNT = 20;
    const MIN_SKILL_90D_BASELINE = 10;
    const MIN_SKILL_365D_BASELINE = 20;
    const CHART_GRID_COLOR = "rgba(195, 198, 215, 0.4)";
    const CHART_BORDER_COLOR = "#94a3b8";
    const CHART_AXIS_TEXT_COLOR = "#434655";

    let liveData = null;
    let historyData = [];
    let metaData = null;
    let currentWeeks = 12;

    Chart.defaults.font.family = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    Chart.defaults.color = "#434655";
    Chart.defaults.borderColor = CHART_BORDER_COLOR;
    Chart.defaults.scale.grid.color = CHART_GRID_COLOR;

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function formatDateTime(value) {
      if (!value) return "---";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat("sv-SE", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      }).format(date);
    }

    function formatDate(value) {
      if (!value) return "---";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat("sv-SE", {
        year: "numeric",
        month: "short",
        day: "numeric"
      }).format(date);
    }

    function formatNumber(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "0";
      return numeric.toLocaleString("sv-SE");
    }

    function formatPercent(value, digits = 1) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "0%";
      return `${numeric.toFixed(digits)}%`;
    }

    function formatSignedNumber(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "";
      if (numeric === 0) return "0";
      const sign = numeric > 0 ? "+" : "−";
      return `${sign}${formatNumber(Math.abs(numeric))}`;
    }

    function formatSignedPercent(value, digits = 1) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "";
      const sign = numeric > 0 ? "+" : "−";
      return `${sign}${Math.abs(numeric).toFixed(digits)}%`;
    }

    function getPercentChange(previousValue, currentValue) {
      const previous = Number(previousValue);
      const current = Number(currentValue);
      if (!Number.isFinite(previous) || !Number.isFinite(current) || previous === 0) return null;
      return ((current - previous) / previous) * 100;
    }

    function clearMetricSupplementaryContent(card) {
      if (!card) return;
      card.querySelectorAll(".metric-delta[data-generated='true']").forEach((element) => element.remove());
    }

    function insertMetricDelta(cardId, currentValue, previousValue, formatter = formatSignedNumber, percentDigits = 1) {
      const card = document.getElementById(cardId);
      if (!card) return;
      clearMetricSupplementaryContent(card);

      const current = Number(currentValue);
      const previous = Number(previousValue);
      if (!Number.isFinite(current) || !Number.isFinite(previous)) return;

      const delta = current - previous;
      if (delta === 0) return;

      const percentChange = getPercentChange(previous, current);
      const deltaElement = document.createElement("p");
      deltaElement.className = "metric-delta";
      deltaElement.dataset.generated = "true";
      deltaElement.style.color = delta > 0 ? "#15803d" : "#b45309";
      deltaElement.textContent = percentChange === null
        ? `${formatter(delta)}`
        : `${formatter(delta)} (${formatSignedPercent(percentChange, percentDigits)})`;

      const valueElement = card.querySelector(".metric-value");
      valueElement?.insertAdjacentElement("afterend", deltaElement);
    }

    function setEntryLevelLegendVisibility(isVisible) {
      const legendItem = document.getElementById("entry-level-legend-item");
      if (legendItem) {
        legendItem.hidden = !isVisible;
      }
    }

    function withTimeout(promiseFactory, timeoutMs = 15000) {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
      return promiseFactory(controller.signal)
        .finally(() => window.clearTimeout(timeout));
    }

    async function fetchLocalJson(path) {
      try {
        const response = await fetch(path, { cache: "no-store" });
        if (!response.ok) return null;
        return await response.json();
      } catch (error) {
        return null;
      }
    }

    function createPipelinePlaceholder() {
      return '<div class="placeholder-box">Data pipeline not yet active. Check back soon.</div>';
    }

    function setSectionUpdated(elementId, value) {
      const element = document.getElementById(elementId);
      if (!element) return;
      element.textContent = value ? formatDateTime(value) : "---";
    }

    function formatWeekLabel(week) {
      if (typeof week !== "string") return "";
      const hyphenIndex = week.indexOf("-");
      return hyphenIndex === -1 ? week : week.slice(hyphenIndex + 1);
    }

    function dedupeOccupationFields(occupationFields = []) {
      const merged = new Map();
      occupationFields.forEach((field) => {
        const key = field.concept_id || field.term || `field-${merged.size}`;
        const current = merged.get(key);
        if (current) {
          current.count += Number(field.count) || 0;
        } else {
          merged.set(key, {
            concept_id: field.concept_id || key,
            term: field.term || "",
            count: Number(field.count) || 0
          });
        }
      });
      return Array.from(merged.values()).sort((a, b) => b.count - a.count);
    }

    function niceNumber(value) {
      if (!Number.isFinite(value) || value <= 0) return 1;
      const exponent = Math.floor(Math.log10(value));
      const fraction = value / (10 ** exponent);
      let niceFraction = 1;
      if (fraction < 1.5) niceFraction = 1;
      else if (fraction < 3) niceFraction = 2;
      else if (fraction < 7) niceFraction = 5;
      else niceFraction = 10;
      return niceFraction * (10 ** exponent);
    }

    function formatCompactNumber(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return "";
      if (numeric < 1000) return formatNumber(numeric);
      return new Intl.NumberFormat("sv-SE", {
        notation: "compact",
        maximumFractionDigits: 1
      }).format(numeric);
    }

    function getLogBounds(values) {
      const numbers = values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value) && value > 0);

      if (!numbers.length) return { min: 1, max: 10 };

      const minValue = Math.min(...numbers);
      const maxValue = Math.max(...numbers);
      const min = 10 ** Math.floor(Math.log10(minValue / 1.25));
      const max = 10 ** Math.ceil(Math.log10(maxValue * 1.25));
      return { min, max };
    }

    function shouldDisplayLogTick(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric) || numeric <= 0) return false;
      const exponent = Math.floor(Math.log10(numeric));
      const mantissa = numeric / (10 ** exponent);
      return [1, 2, 5].some((allowed) => Math.abs(mantissa - allowed) < 0.0001);
    }

    function truncateLabel(value, maxLength = 32) {
      const text = String(value ?? "");
      return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
    }

    function getLineYAxisBounds(datasets) {
      const values = datasets
        .flatMap((dataset) => dataset.data)
        .map((value) => {
          if (value === null || value === undefined) return Number.NaN;
          if (typeof value === "object") return Number(value.y);
          return Number(value);
        })
        .filter((value) => Number.isFinite(value));

      if (!values.length) return {};

      const minValue = Math.min(...values);
      const maxValue = Math.max(...values);
      const spread = maxValue - minValue;
      const padding = spread === 0 ? Math.max(Math.abs(maxValue) * 0.1, 1) : spread * 0.1;
      const minTarget = minValue * 0.9;
      const maxTarget = maxValue + padding;
      const step = niceNumber(((maxTarget - minTarget) || Math.max(Math.abs(maxValue), 1)) / 5);

      let min = Math.floor(minTarget / step) * step;
      let max = Math.ceil(maxTarget / step) * step;

      if (min === max) max = min + step;
      return { min, max };
    }

    function setCanvasHeight(id, itemCount, base = 320, perItem = 30) {
      const canvas = document.getElementById(id);
      if (!canvas) return;
      const desktopHeight = Math.max(base, itemCount * perItem);
      const useHeight = window.innerWidth < 768 ? Math.round(desktopHeight * 1.2) : desktopHeight;
      // Use setProperty with "important" to override the CSS height: !important rule on canvas classes.
      canvas.style.setProperty("height", `${useHeight}px`, "important");
    }

    function updateStalenessBadge() {
      const badge = document.getElementById("live-badge");
      const badgeText = document.getElementById("live-badge-text");
      if (!badge || !badgeText) return;
      badge.classList.remove("live-badge--stale");
      badgeText.textContent = "Live data";

      const updatedAt = metaData?.last_updated ? new Date(metaData.last_updated) : null;
      if (!updatedAt || Number.isNaN(updatedAt.getTime())) return;

      const ageInDays = (Date.now() - updatedAt.getTime()) / (1000 * 60 * 60 * 24);
      if (ageInDays > 10) {
        badge.classList.add("live-badge--stale");
        badgeText.textContent = "Data may be outdated";
      }
    }

    function destroyChart(id) {
      if (charts[id]) {
        charts[id].destroy();
        delete charts[id];
      }
    }

    function renderLineChart(id, labels, datasets, extraOptions = {}) {
      destroyChart(id);
      const canvas = document.getElementById(id);
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const yAxisBounds = getLineYAxisBounds(datasets);
      charts[id] = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: "index",
            intersect: false,
            ...extraOptions.interaction
          },
          plugins: {
            legend: { display: false },
            tooltip: { enabled: true },
            ...extraOptions.plugins
          },
          elements: {
            point: {
              radius: labels.length < 30 ? 3 : 0,
              hoverRadius: 6
            }
          },
          scales: {
            x: {
              display: true,
              grid: { display: false },
              ticks: {
                maxRotation: 0,
                autoSkip: true,
                maxTicksLimit: 6,
                font: { size: window.innerWidth < 640 ? 10 : 11 },
                color: "#434655"
              },
              ...extraOptions.scales?.x
            },
            y: {
              min: yAxisBounds.min,
              max: yAxisBounds.max,
              ticks: {
                font: { size: window.innerWidth < 640 ? 10 : 11 },
                color: CHART_AXIS_TEXT_COLOR,
                callback: (value) => Number(value).toLocaleString("sv-SE")
              },
              grid: { color: CHART_GRID_COLOR },
              ...extraOptions.scales?.y
            }
          }
        }
      });
    }

    function renderHorizontalBarChart(id, labels, data, color = "#2563eb", options = {}) {
      destroyChart(id);
      const canvas = document.getElementById(id);
      if (!canvas) return;
      setCanvasHeight(id, labels.length);
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const isCompact = window.innerWidth < 768;
      const barAxisFontSize = isCompact ? 10 : 13;
      const xScaleOptions = options.scales?.x || {};
      const yScaleOptions = options.scales?.y || {};
      const xTickOptions = xScaleOptions.ticks || {};
      const yTickOptions = yScaleOptions.ticks || {};
      const customAfterFit = yScaleOptions.afterFit;
      charts[id] = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [{
            data,
            backgroundColor: color,
            borderRadius: 4,
            barThickness: 14,
            ...options.dataset
          }]
        },
        plugins: options.chartPlugins || [],
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          layout: {
            padding: {
              left: isCompact ? 4 : 16,
              right: 8
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: { enabled: true },
            ...options.plugins
          },
          scales: {
            x: {
              ...xScaleOptions,
              grid: { color: CHART_GRID_COLOR },
              ticks: {
                font: { size: barAxisFontSize },
                color: CHART_AXIS_TEXT_COLOR,
                callback: (value) => Number(value).toLocaleString("sv-SE"),
                ...xTickOptions
              }
            },
            y: {
              ...yScaleOptions,
              grid: { display: false },
              afterFit(scale) {
                scale.width = Math.max(scale.width, isCompact ? 120 : 210);
                if (typeof customAfterFit === "function") customAfterFit(scale);
              },
              ticks: {
                font: { size: barAxisFontSize },
                color: CHART_AXIS_TEXT_COLOR,
                callback: (value, index) => truncateLabel(labels[index] || value, isCompact ? 18 : 34),
                ...yTickOptions
              }
            }
          },
          ...options.chart
        }
      });
    }

    function buildSmoothSparklinePath(points) {
      if (points.length === 1) {
        return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
      }

      let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
      for (let index = 0; index < points.length - 1; index += 1) {
        const current = points[index];
        const next = points[index + 1];
        const previous = points[index - 1] || current;
        const afterNext = points[index + 2] || next;
        const cp1x = current.x + ((next.x - previous.x) / 6);
        const cp1y = current.y + ((next.y - previous.y) / 6);
        const cp2x = next.x - ((afterNext.x - current.x) / 6);
        const cp2y = next.y - ((afterNext.y - current.y) / 6);
        path += ` C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)}, ${cp2x.toFixed(2)} ${cp2y.toFixed(2)}, ${next.x.toFixed(2)} ${next.y.toFixed(2)}`;
      }
      return path;
    }

    function buildSparkline(values) {
      const series = values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));

      if (!series.length) {
        return '<svg class="sparkline" viewBox="0 0 120 40" aria-hidden="true"></svg>';
      }

      const width = 120;
      const height = 40;
      const min = Math.min(...series);
      const max = Math.max(...series);
      const range = max - min || 1;

      const points = series.map((value, index) => {
        const x = series.length === 1 ? width / 2 : (index / (series.length - 1)) * width;
        const y = height - (((value - min) / range) * (height - 6)) - 3;
        return { x, y };
      });
      const path = buildSmoothSparklinePath(points);

      return `
        <svg class="sparkline" viewBox="0 0 120 40" aria-hidden="true">
          <path d="${path}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        </svg>
      `;
    }

    function hideLoading() {
      document.getElementById("loading-overlay").classList.add("hidden");
    }

    function showErrorOverlay() {
      document.getElementById("error-overlay").classList.remove("hidden");
    }

    function renderLivePulseSection() {
      const headerLastUpdated = document.getElementById("header-last-updated");
      if (headerLastUpdated) {
        headerLastUpdated.textContent = formatDateTime(metaData?.last_updated);
      }
      document.getElementById("live-pulse-updated").textContent = formatDateTime(metaData?.last_updated);
      updateStalenessBadge();

      [
        "metric-card-total-ads",
        "metric-card-total-positions",
        "metric-card-remote-ads",
        "metric-card-remote-share",
        "metric-card-entry-level"
      ].forEach((cardId) => clearMetricSupplementaryContent(document.getElementById(cardId)));

      document.getElementById("metric-total-ads").textContent = formatNumber(liveData.total_ads);
      document.getElementById("metric-total-positions").textContent = formatNumber(liveData.total_positions);
      document.getElementById("metric-remote-ads").textContent = formatNumber(liveData.remote_ads);

      const remoteShare = liveData.total_ads ? (liveData.remote_ads / liveData.total_ads) * 100 : 0;
      document.getElementById("metric-remote-share").textContent = formatPercent(remoteShare);
      const entryLevelCard = document.getElementById("metric-card-entry-level");
      const entryLevelShareNote = document.getElementById("metric-entry-level-share");
      if (liveData.entry_level_ads === undefined || liveData.entry_level_ads === null) {
        entryLevelCard.hidden = true;
      } else {
        entryLevelCard.hidden = false;
        document.getElementById("metric-entry-level-ads").textContent = formatNumber(liveData.entry_level_ads);
        const entryLevelShare = liveData.total_ads ? (liveData.entry_level_ads / liveData.total_ads) * 100 : 0;
        entryLevelShareNote.textContent = `${entryLevelShare.toFixed(1)}% of all ads`;
      }

      const secondaryMetrics = document.getElementById("secondary-metrics");
      const secondaryItems = [];
      if (liveData.trainee_ads !== undefined && liveData.trainee_ads !== null) {
        secondaryItems.push(`<span>Trainee positions: <strong>${escapeHtml(formatNumber(liveData.trainee_ads))}</strong></span>`);
      }
      if (liveData.larling_ads !== undefined && liveData.larling_ads !== null) {
        secondaryItems.push(`<span>Apprenticeship / lärling: <strong>${escapeHtml(formatNumber(liveData.larling_ads))}</strong></span>`);
      }
      secondaryMetrics.hidden = secondaryItems.length === 0;
      secondaryMetrics.innerHTML = secondaryItems.join("");

      if (historyData.length >= 2) {
        const previousSnapshot = historyData[historyData.length - 2];
        const currentSnapshot = historyData[historyData.length - 1];
        insertMetricDelta("metric-card-total-ads", currentSnapshot.total_ads, previousSnapshot.total_ads);
        insertMetricDelta("metric-card-total-positions", currentSnapshot.total_positions, previousSnapshot.total_positions);
        insertMetricDelta("metric-card-remote-ads", currentSnapshot.remote_ads, previousSnapshot.remote_ads);

        const previousRemoteShare = previousSnapshot.total_ads
          ? (previousSnapshot.remote_ads / previousSnapshot.total_ads) * 100
          : 0;
        const currentRemoteShare = currentSnapshot.total_ads
          ? (currentSnapshot.remote_ads / currentSnapshot.total_ads) * 100
          : 0;
        insertMetricDelta("metric-card-remote-share", currentRemoteShare, previousRemoteShare, (value) => formatSignedPercent(value, 1));

        if (
          currentSnapshot.entry_level_ads !== undefined && currentSnapshot.entry_level_ads !== null &&
          previousSnapshot.entry_level_ads !== undefined && previousSnapshot.entry_level_ads !== null
        ) {
          insertMetricDelta(
            "metric-card-entry-level",
            currentSnapshot.entry_level_ads,
            previousSnapshot.entry_level_ads
          );
        }
      }
      setEntryLevelLegendVisibility(false);

      const trendNote = document.getElementById("trend-note");

      // Zero-entry case: history file loaded but contains no snapshots yet.
      if (historyData.length === 0) {
        disableTimeframeButtons();
        trendNote.hidden = false;
        trendNote.textContent = "No data available yet.";
        renderLivePulseStaticCharts();
        // Do not render time-series charts — no data to plot.
        return;
      }

      if (historyData.length === 1) {
        disableTimeframeButtons();
        trendNote.hidden = false;
        trendNote.textContent = "More data needed for trend view.";
      } else {
        trendNote.hidden = true;
      }

      renderLivePulseStaticCharts();
      updateTimeframeCharts();
    }

    function updateTimeframeCharts() {
      if (!historyData.length) return;
      const dataToUse = currentWeeks === 0 ? historyData : historyData.slice(-currentWeeks);
      const labels = dataToUse.map((snapshot) => formatWeekLabel(snapshot.week));

      renderLineChart("chart-ads-timeline", labels, [{
        label: "Active ads",
        data: dataToUse.map((snapshot) => snapshot.total_ads),
        borderColor: "#2563eb",
        backgroundColor: "rgba(0, 74, 198, 0.08)",
        borderWidth: 3,
        fill: true,
        tension: 0.3
      }]);

      renderLineChart("chart-ads-vs-positions", labels, [
        {
          label: "Active ads",
          data: dataToUse.map((snapshot) => snapshot.total_ads),
          borderColor: "#2563eb",
          borderWidth: 3,
          tension: 0.3
        },
        {
          label: "Open positions",
          data: dataToUse.map((snapshot) => snapshot.total_positions),
          borderColor: "#006a61",
          borderWidth: 2,
          tension: 0.3
        }
      ]);

      const remoteShareDatasets = [{
        label: "Remote share",
        data: dataToUse.map((snapshot) => snapshot.total_ads ? (snapshot.remote_ads / snapshot.total_ads) * 100 : 0),
        borderColor: "#2563eb",
        borderWidth: 3,
        tension: 0.3
      }];

      const validEntryLevelPoints = dataToUse.filter((snapshot) => (
        snapshot.entry_level_ads !== undefined &&
        snapshot.entry_level_ads !== null &&
        snapshot.total_ads
      ));

      if (validEntryLevelPoints.length >= 2) {
        remoteShareDatasets.push({
          label: "Entry-level share",
          data: validEntryLevelPoints.map((snapshot) => ({
            x: formatWeekLabel(snapshot.week),
            y: (snapshot.entry_level_ads / snapshot.total_ads) * 100
          })),
          borderColor: "#7c3aed",
          borderWidth: 2,
          tension: 0.3,
          spanGaps: false
        });
        setEntryLevelLegendVisibility(true);
      } else {
        setEntryLevelLegendVisibility(false);
      }

      renderLineChart("chart-remote-timeline", labels, remoteShareDatasets, {
        scales: {
          y: {
            ticks: {
              callback: (value) => `${value.toFixed ? value.toFixed(0) : value}%`
            }
          }
        }
      });
    }

    function renderLivePulseStaticCharts() {
      const sectorData = dedupeOccupationFields(liveData.by_occupation_field || []).slice(0, 10);
      renderHorizontalBarChart(
        "chart-sectors",
        sectorData.map((entry) => entry.term),
        sectorData.map((entry) => entry.count),
        "#2563eb"
      );

      const regionData = [...(liveData.by_region || [])]
        .sort((left, right) => right.count - left.count)
        .slice(0, 10);

      renderHorizontalBarChart(
        "chart-regions",
        regionData.map((entry) => entry.term),
        regionData.map((entry) => entry.count),
        "#006a61"
      );

      const remoteConcentrationCanvas = document.getElementById("chart-remote-concentration");
      const remoteConcentrationEmpty = document.getElementById("chart-remote-concentration-empty");
      const nationalRemoteShare = liveData.total_ads ? (liveData.remote_ads / liveData.total_ads) : 0;
      const concentrationData = (liveData.remote_by_field || []).map((rf) => {
        const totalField = (liveData.by_occupation_field || []).find(
          (field) => field.concept_id === rf.concept_id
        );
        const fieldTotal = totalField ? Number(totalField.count) : Number(rf.count);
        const fieldRemoteShare = fieldTotal > 0 ? Number(rf.count) / fieldTotal : 0;
        const index = nationalRemoteShare > 0
          ? fieldRemoteShare / nationalRemoteShare
          : 0;
        return { term: rf.term, index: parseFloat(index.toFixed(2)) };
      }).filter((entry) => entry.index > 0).sort((left, right) => right.index - left.index);

      if (!concentrationData.length) {
        destroyChart("chart-remote-concentration");
        if (remoteConcentrationCanvas) remoteConcentrationCanvas.hidden = true;
        if (remoteConcentrationEmpty) remoteConcentrationEmpty.hidden = false;
        return;
      }

      if (remoteConcentrationCanvas) remoteConcentrationCanvas.hidden = false;
      if (remoteConcentrationEmpty) remoteConcentrationEmpty.hidden = true;
      const maxConcentrationIndex = Math.max(...concentrationData.map((entry) => entry.index), 1);

      const referenceLinePlugin = {
        id: "referenceLine",
        afterDraw(chart) {
          const ctx = chart.ctx;
          const xScale = chart.scales.x;
          if (!xScale) return;
          const x = xScale.getPixelForValue(1);
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x, chart.chartArea.top);
          ctx.lineTo(x, chart.chartArea.bottom);
          ctx.strokeStyle = "rgba(195,198,215,0.6)";
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.restore();
        }
      };

      renderHorizontalBarChart(
        "chart-remote-concentration",
        concentrationData.map((entry) => entry.term),
        concentrationData.map((entry) => entry.index),
        concentrationData.map((entry) => entry.index >= 1 ? "#2563eb" : "#006a61"),
        {
          chartPlugins: [referenceLinePlugin],
          scales: {
            x: {
              min: 0,
              max: Math.max(1.2, Math.ceil(maxConcentrationIndex * 10) / 10),
              ticks: {
                callback: (value) => Number(value).toFixed(1)
              }
            }
          }
        }
      );

      const entryLevelCanvas = document.getElementById("chart-entry-level-sectors");
      const entryLevelEmpty = document.getElementById("chart-entry-level-empty");
      const entryLevelData = [...(liveData.entry_by_field || [])]
        .map((entry) => ({
          term: entry.term,
          count: Number(entry.count) || 0
        }))
        .filter((entry) => entry.count > 0)
        .sort((left, right) => right.count - left.count)
        .slice(0, 10);

      if (!entryLevelData.length) {
        destroyChart("chart-entry-level-sectors");
        if (entryLevelCanvas) entryLevelCanvas.hidden = true;
        if (entryLevelEmpty) entryLevelEmpty.hidden = false;
        return;
      }

      if (entryLevelCanvas) entryLevelCanvas.hidden = false;
      if (entryLevelEmpty) entryLevelEmpty.hidden = true;

      renderHorizontalBarChart(
        "chart-entry-level-sectors",
        entryLevelData.map((entry) => entry.term),
        entryLevelData.map((entry) => entry.count),
        "#7c3aed"
      );
    }

    function disableTimeframeButtons() {
      document.querySelectorAll("#timeframe-selector button").forEach((button) => {
        button.disabled = true;
      });
    }

    function setActiveTimeframeButton(activeButton) {
      document.querySelectorAll("#timeframe-selector button").forEach((button) => {
        button.classList.toggle("is-active", button === activeButton);
      });
    }

    function getSectionTimestamp(data) {
      return data?.last_updated || data?.generated || data?.week || data?.date || null;
    }

    function renderOptionalSections(datasetMap) {
      OPTIONAL_SECTION_CONFIG.forEach((config) => {
        const container = document.getElementById(config.bodyElementId);
        const data = datasetMap[config.key];
        if (!data) {
          container.innerHTML = createPipelinePlaceholder();
          return;
        }

        setSectionUpdated(config.updatedElementId, getSectionTimestamp(data));

        try {
          config.renderer(container, data);
        } catch (error) {
          console.error(`Could not render ${config.key}`, error);
          container.innerHTML = createPipelinePlaceholder();
        }
      });
    }

    function renderOccupationDecaySection(container, data) {
      if (!Array.isArray(data?.years) || !Array.isArray(data?.occupation_fields) || !data.occupation_fields.length) {
        container.innerHTML = createPipelinePlaceholder();
        return;
      }

      container.innerHTML = `
        <div class="section-surface">
          <div class="decay-controls">
            <div class="control-chip-row" id="decay-view-toggle">
              <button class="control-chip is-active" type="button" data-mode="absolute">Absolute counts</button>
              <button class="control-chip" type="button" data-mode="indexed">Indexed to start</button>
            </div>
            <div class="helper-copy">Each row is one occupation field, sorted by most recent volume. Darker cells = more ads that year. Hover a cell for the exact figure.</div>
            <div class="methodology-note">
              Counts reflect ads that were posted and removed in each year. A decline may indicate lower demand or faster hiring, not necessarily fewer roles.
            </div>
          </div>
          <div class="heatmap-wrap" id="occupation-decay-heatmap"></div>
          <div class="insight-grid" id="occupation-decay-insights"></div>
        </div>
      `;

      let mode = "absolute";

      const sortedFields = [...data.occupation_fields].sort((a, b) => {
        const aLast = Number(a.by_year[a.by_year.length - 1]) || 0;
        const bLast = Number(b.by_year[b.by_year.length - 1]) || 0;
        return bLast - aLast;
      });

      function getSeries(field) {
        const values = (field.by_year || []).map((value) => Number(value) || 0);
        if (mode === "absolute") return values;
        const startValue = values.find((value) => value > 0) || values[0] || 1;
        return values.map((value) => Math.round((value / startValue) * 100));
      }

      function renderInsights() {
        const latestYear = data.years[data.years.length - 1];
        const displayYear = Math.max(Number(latestYear) || 0, new Date().getFullYear());
        const declines = data.occupation_fields
          .map((field) => {
            const values = (field.by_year || []).map((value) => Number(value) || 0);
            const peak = Math.max(...values);
            const current = values[values.length - 1] || 0;
            const peakIndex = values.indexOf(peak);
            const change = peak > 0 ? ((current - peak) / peak) * 100 : 0;
            return { field, peak, peakYear: data.years[peakIndex], current, change };
          })
          .filter((item) => item.change < 0)
          .sort((left, right) => left.change - right.change)
          .slice(0, 3);

        const growth = data.occupation_fields
          .map((field) => {
            const values = (field.by_year || []).map((value) => Number(value) || 0);
            const floor = values.find((value) => value > 0) || 1;
            const current = values[values.length - 1] || 0;
            const min = Math.min(...values.filter((value) => value > 0), floor);
            const change = min > 0 ? ((current - min) / min) * 100 : 0;
            return { field, min, current, change };
          })
          .filter((item) => item.change > 0)
          .sort((left, right) => right.change - left.change)
          .slice(0, 3);

        document.getElementById("occupation-decay-insights").innerHTML = `
          <div class="insight-row">
            <h3 class="insight-row-title">Biggest pullbacks from peak to ${displayYear}</h3>
            <div class="insight-cards">
              ${declines.map((item) => `
                <article class="insight-card">
                  <p class="insight-label">${escapeHtml(item.field.term)}</p>
                  <p class="insight-value negative-text">${formatPercent(item.change)}</p>
                  <p class="insight-meta">Peak ${item.peakYear}: ${formatNumber(item.peak)}<br>Current: ${formatNumber(item.current)}</p>
                </article>
              `).join("")}
            </div>
          </div>
          <div class="insight-row">
            <h3 class="insight-row-title">Fastest growth from trough to ${displayYear}</h3>
            <div class="insight-cards">
              ${growth.map((item) => `
                <article class="insight-card">
                  <p class="insight-label">${escapeHtml(item.field.term)}</p>
                  <p class="insight-value positive-text">+${formatPercent(item.change)}</p>
                  <p class="insight-meta">Lowest point: ${formatNumber(item.min)}<br>Current: ${formatNumber(item.current)}</p>
                </article>
              `).join("")}
            </div>
          </div>
        `;
      }

      function render() {
        const heatmap = document.getElementById("occupation-decay-heatmap");
        if (!heatmap) return;

        const headers = data.years.map((y) => `<th>${y}</th>`).join("");

        const rows = sortedFields.map((field) => {
          const values = getSeries(field);
          const rowMax = Math.max(...values, 1);
          const cells = values.map((v, yi) => {
            const norm = rowMax > 0 ? v / rowMax : 0;
            const opacity = 0.06 + norm * 0.78;
            const bg = `rgba(37,99,235,${opacity.toFixed(2)})`;
            const textColor = norm > 0.52 ? "#ffffff" : "#1c1b1b";
            const rawCount = Number(field.by_year[yi]) || 0;
            const titleText = mode === "absolute"
              ? `${field.term} — ${data.years[yi]}: ${formatNumber(rawCount)}`
              : `${field.term} — ${data.years[yi]}: ${v} (index, 100 = start year)`;
            const display = mode === "absolute"
              ? formatCompactNumber(rawCount)
              : `${v}`;
            return `<td style="background:${bg};color:${textColor}" title="${escapeHtml(titleText)}">${escapeHtml(display)}</td>`;
          }).join("");

          return `<tr>
            <td class="heatmap-name">${escapeHtml(truncateLabel(field.term, 30))}</td>
            ${cells}
          </tr>`;
        }).join("");

        heatmap.innerHTML = `
          <table class="heatmap-table">
            <thead><tr><th></th>${headers}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        `;

        renderInsights();
      }

      Array.from(document.querySelectorAll("#decay-view-toggle .control-chip")).forEach((button) => {
        button.addEventListener("click", () => {
          mode = button.dataset.mode;
          document.querySelectorAll("#decay-view-toggle .control-chip").forEach((item) => {
            item.classList.toggle("is-active", item === button);
          });
          render();
        });
      });


      render();
    }

    function renderSkillVelocitySection(container, data) {
      if (!Array.isArray(data?.months) || !Array.isArray(data?.skills) || !data.skills.length) {
        container.innerHTML = createPipelinePlaceholder();
        return;
      }

      container.innerHTML = `
        <div class="section-surface">
          <div class="skill-controls">
            <div class="tab-row" id="skill-tab-row">
              <button class="tab-button is-active" type="button" data-tab="all">All skills</button>
              <button class="tab-button" type="button" data-tab="technical">Technical skills</button>
              <button class="tab-button" type="button" data-tab="healthcare">Healthcare skills</button>
            </div>
            <div class="sort-row" id="skill-sort-row">
              <button class="sort-button is-active" type="button" data-sort="growth90">Fastest growing (90 days)</button>
              <button class="sort-button" type="button" data-sort="growth365">Fastest growing (365 days)</button>
              <button class="sort-button" type="button" data-sort="volume">Highest volume</button>
              <button class="sort-button" type="button" data-sort="newest">Newest</button>
              <button class="sort-button" type="button" data-sort="declining">Declining</button>
            </div>
            <label class="explorer-field">
              <span class="explorer-label">Filter skills</span>
              <input class="skill-filter-input" id="skill-filter-input" type="search" placeholder="Type a skill name">
            </label>
            <div class="helper-copy">Rankings exclude skills with fewer than ${MIN_SKILL_CURRENT_COUNT} mentions in the latest archived month to reduce tiny-sample noise.</div>
          </div>
          <div class="skill-list" id="skill-list"></div>
        </div>
      `;

      let activeTab = "all";
      let activeSort = "growth90";
      let search = "";
      let expandedId = "";
      let showAll = false;

      const technicalIds = new Set(data.technical_skill_ids || []);
      const healthcareIds = new Set(data.healthcare_skill_ids || []);

      function matchesTab(skill) {
        if (activeTab === "all") return true;
        if (activeTab === "technical") return technicalIds.size ? technicalIds.has(skill.concept_id) : true;
        if (activeTab === "healthcare") return healthcareIds.size ? healthcareIds.has(skill.concept_id) : true;
        return true;
      }

      function sortSkills(items) {
        const latestValue = (skill) => Number(skill.latest_count ?? skill.monthly_counts?.[skill.monthly_counts.length - 1]) || 0;
        return [...items].sort((left, right) => {
          if (activeSort === "growth365") return (right.growth_365d || 0) - (left.growth_365d || 0);
          if (activeSort === "volume") return latestValue(right) - latestValue(left);
          if (activeSort === "newest") return String(right.first_seen || "").localeCompare(String(left.first_seen || ""));
          if (activeSort === "declining") return (left.growth_90d || 0) - (right.growth_90d || 0);
          return (right.growth_90d || 0) - (left.growth_90d || 0);
        });
      }

      function getPreviousWindowTotal(skill, months) {
        const series = Array.isArray(skill.monthly_counts) ? skill.monthly_counts : [];
        const currentWindowStart = Math.max(0, series.length - months);
        const previousWindowStart = Math.max(0, currentWindowStart - months);
        return series
          .slice(previousWindowStart, currentWindowStart)
          .reduce((sum, value) => sum + (Number(value) || 0), 0);
      }

      function meetsSkillRankingThreshold(skill) {
        const latestCount = Number(skill.latest_count ?? skill.monthly_counts?.[skill.monthly_counts.length - 1]) || 0;
        if (latestCount < MIN_SKILL_CURRENT_COUNT) {
          return false;
        }

        if (activeSort === "growth90" || activeSort === "declining") {
          return getPreviousWindowTotal(skill, 3) >= MIN_SKILL_90D_BASELINE;
        }

        if (activeSort === "growth365") {
          return getPreviousWindowTotal(skill, 12) >= MIN_SKILL_365D_BASELINE;
        }

        return true;
      }

      function getSkillThresholdCopy() {
        if (activeSort === "growth90" || activeSort === "declining") {
          return `Rankings require at least ${MIN_SKILL_CURRENT_COUNT} mentions in the latest archived month and at least ${MIN_SKILL_90D_BASELINE} mentions in the prior 90-day comparison window.`;
        }
        if (activeSort === "growth365") {
          return `Rankings require at least ${MIN_SKILL_CURRENT_COUNT} mentions in the latest archived month and at least ${MIN_SKILL_365D_BASELINE} mentions in the prior 12-month comparison window.`;
        }
        return `Rankings require at least ${MIN_SKILL_CURRENT_COUNT} mentions in the latest archived month.`;
      }

      function renderExpandedChart(skill) {
        const detailId = `skill-chart-${skill.concept_id}`;
        const existing = document.getElementById(detailId);
        if (!existing) return;

        renderLineChart(detailId, data.months, [{
          label: skill.term,
          data: skill.monthly_counts,
          borderColor: "#2563eb",
          backgroundColor: "rgba(0, 74, 198, 0.08)",
          borderWidth: 3,
          fill: true,
          tension: 0.26
        }]);
      }

      function renderList() {
        const filtered = sortSkills(
          data.skills.filter((skill) => {
            return (
              matchesTab(skill) &&
              meetsSkillRankingThreshold(skill) &&
              skill.term.toLowerCase().includes(search)
            );
          })
        );

        const list = document.getElementById("skill-list");
        const helperCopy = container.querySelector(".skill-controls .helper-copy");
        if (helperCopy) {
          helperCopy.textContent = getSkillThresholdCopy();
        }
        if (!filtered.length) {
          list.innerHTML = `<div class="placeholder-box">No ranked skills match the current filters. ${escapeHtml(getSkillThresholdCopy())}</div>`;
          return;
        }

        const visibleSkills = showAll ? filtered : filtered.slice(0, 10);
        if (!visibleSkills.some((skill) => skill.concept_id === expandedId)) {
          expandedId = "";
        }

        list.innerHTML = `
          <div class="skill-list-header" aria-hidden="true">
            <span>#</span>
            <span>Skill</span>
            <span>Trend</span>
            <span>Growth (90d)</span>
            <span>Growth (1yr)</span>
            <span>Mentions</span>
          </div>
        ` + visibleSkills.map((skill, index) => {
          const lastYear = (skill.monthly_counts || []).slice(-12);
          const latestCount = Number(skill.latest_count ?? (skill.monthly_counts || []).slice(-1)[0]) || 0;
          const expanded = expandedId === skill.concept_id;
          return `
            <article class="skill-item">
              <button class="skill-row-button" type="button" data-skill-id="${escapeHtml(skill.concept_id)}">
                <span class="skill-rank">#${index + 1}</span>
                <div>
                  <p class="skill-name">${escapeHtml(skill.term)}</p>
                  <p class="skill-meta">First seen ${escapeHtml(skill.first_seen || "—")} · Peak ${escapeHtml(skill.peak_month || "—")}</p>
                </div>
                <div>${buildSparkline(lastYear)}</div>
                <div class="${(skill.growth_90d || 0) >= 0 ? "positive-text" : "negative-text"}">${skill.growth_90d >= 0 ? "+" : ""}${formatPercent(skill.growth_90d || 0)}</div>
                <div class="${(skill.growth_365d || 0) >= 0 ? "positive-text" : "negative-text"}">${skill.growth_365d >= 0 ? "+" : ""}${formatPercent(skill.growth_365d || 0)}</div>
                <div>${formatNumber(latestCount)}</div>
              </button>
              ${expanded ? `
                <div class="skill-detail">
                  <div class="skill-detail-head">
                    <p class="helper-copy" style="margin:0;">Full history for ${escapeHtml(skill.term)}</p>
                    <button class="secondary-button" data-close-skill="${escapeHtml(skill.concept_id)}" type="button">Close</button>
                  </div>
                  <canvas class="skill-chart-canvas" id="skill-chart-${escapeHtml(skill.concept_id)}"></canvas>
                </div>
              ` : ""}
            </article>
          `;
        }).join("") + (
          filtered.length > 10
            ? `
              <div class="skill-list-footer">
                <button class="secondary-button" id="skill-show-more-button" type="button">
                  ${showAll ? "Show fewer" : `Show more (${filtered.length - 10} more)`}
                </button>
              </div>
            `
            : ""
        );

        list.querySelectorAll("[data-skill-id]").forEach((button) => {
          button.addEventListener("click", () => {
            expandedId = expandedId === button.dataset.skillId ? "" : button.dataset.skillId;
            renderList();
          });
        });

        list.querySelectorAll("[data-close-skill]").forEach((button) => {
          button.addEventListener("click", (event) => {
            event.stopPropagation();
            expandedId = "";
            renderList();
          });
        });

        const showMoreButton = document.getElementById("skill-show-more-button");
        if (showMoreButton) {
          showMoreButton.addEventListener("click", () => {
            showAll = !showAll;
            renderList();
          });
        }

        visibleSkills.forEach((skill) => {
          if (expandedId === skill.concept_id) renderExpandedChart(skill);
        });
      }

      document.getElementById("skill-filter-input").addEventListener("input", (event) => {
        search = event.target.value.trim().toLowerCase();
        showAll = false;
        renderList();
      });

      document.querySelectorAll("#skill-tab-row .tab-button").forEach((button) => {
        button.addEventListener("click", () => {
          activeTab = button.dataset.tab;
          showAll = false;
          document.querySelectorAll("#skill-tab-row .tab-button").forEach((item) => {
            item.classList.toggle("is-active", item === button);
          });
          renderList();
        });
      });

      document.querySelectorAll("#skill-sort-row .sort-button").forEach((button) => {
        button.addEventListener("click", () => {
          activeSort = button.dataset.sort;
          showAll = false;
          document.querySelectorAll("#skill-sort-row .sort-button").forEach((item) => {
            item.classList.toggle("is-active", item === button);
          });
          renderList();
        });
      });

      renderList();
    }

    function renderDemandGapSection(container, data) {
      if (!Array.isArray(data?.occupations) || !data.occupations.length) {
        container.innerHTML = createPipelinePlaceholder();
        return;
      }

      container.innerHTML = `
        <div class="section-surface">
          <canvas class="scatter-canvas" id="demand-gap-chart"></canvas>
          <div class="callout-grid" id="demand-gap-callouts"></div>
        </div>
      `;

      const occupations = data.occupations
        .filter((entry) => Number(entry.ad_count) > 0 && Number(entry.search_count) > 0)
        .map((entry) => ({
          ...entry,
          x: Number(entry.search_count),
          y: Number(entry.ad_count)
        }));

      const searchValues = occupations.map((entry) => entry.x).sort((left, right) => left - right);
      const adValues = occupations.map((entry) => entry.y).sort((left, right) => left - right);
      const medianX = searchValues[Math.floor(searchValues.length / 2)] || 1;
      const medianY = adValues[Math.floor(adValues.length / 2)] || 1;
      const xBounds = getLogBounds(searchValues);
      const yBounds = getLogBounds(adValues);

      const quadrantPlugin = {
        id: "quadrantPlugin",
        afterDraw(chart) {
          const { ctx, chartArea, scales } = chart;
          if (!chartArea) return;
          const medianXPx = scales.x.getPixelForValue(medianX);
          const medianYPx = scales.y.getPixelForValue(medianY);

          ctx.save();
          ctx.strokeStyle = CHART_GRID_COLOR;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(medianXPx, chartArea.top);
          ctx.lineTo(medianXPx, chartArea.bottom);
          ctx.moveTo(chartArea.left, medianYPx);
          ctx.lineTo(chartArea.right, medianYPx);
          ctx.stroke();

          const labelFontSize = window.innerWidth < 640 ? 14 : 18;
          ctx.fillStyle = "rgba(67, 70, 85, 0.8)";
          ctx.font = `600 ${labelFontSize}px Inter, sans-serif`;
          ctx.textAlign = "center";
          const topLeftX = (chartArea.left + medianXPx) / 2;
          const topRightX = (medianXPx + chartArea.right) / 2;
          const topY = chartArea.top + Math.max((medianYPx - chartArea.top) * 0.28, 34);
          const bottomY = medianYPx + ((chartArea.bottom - medianYPx) * 0.55);
          const lineGap = window.innerWidth < 640 ? 16 : 18;

          ctx.fillText("Hidden opportunities", topLeftX, topY);
          ctx.fillText("Competitive", topRightX, topY - (lineGap / 2));
          ctx.fillText("active market", topRightX, topY + (lineGap / 2));
          ctx.fillText("Quiet corners", topLeftX, bottomY);
          ctx.fillText("Competitive crowd", topRightX, bottomY);
          ctx.restore();
        }
      };

      destroyChart("demand-gap-chart");
      charts["demand-gap-chart"] = new Chart(document.getElementById("demand-gap-chart").getContext("2d"), {
        type: "scatter",
        data: {
          datasets: [{
            data: occupations.map((entry) => ({
              x: entry.x,
              y: entry.y,
              term: entry.term,
              gapRatio: entry.gap_ratio
            })),
            pointRadius: 5,
            pointHoverRadius: 7,
            backgroundColor(context) {
              const raw = context.raw || {};
              if (raw.x <= medianX && raw.y >= medianY) return "rgba(0, 106, 97, 0.72)";
              if (raw.x >= medianX && raw.y >= medianY) return "rgba(37, 99, 235, 0.72)";
              if (raw.x >= medianX && raw.y <= medianY) return "rgba(180, 83, 9, 0.72)";
              return "rgba(107, 114, 128, 0.72)";
            }
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label(context) {
                  const raw = context.raw || {};
                  return `${raw.term}: ${formatNumber(raw.y)} ads · ${formatNumber(raw.x)} searches · ${Number(raw.gapRatio || 0).toFixed(2)} ratio`;
                }
              }
            }
          },
          scales: {
            x: {
              type: "logarithmic",
              min: xBounds.min,
              max: xBounds.max,
              ticks: {
                color: "#434655",
                font: { size: window.innerWidth < 640 ? 10 : 11 },
                maxTicksLimit: 8,
                callback: (value) => shouldDisplayLogTick(value) ? formatCompactNumber(value) : ""
              },
              title: {
                display: true,
                text: "Search count"
              }
            },
            y: {
              type: "logarithmic",
              min: yBounds.min,
              max: yBounds.max,
              ticks: {
                color: "#434655",
                font: { size: window.innerWidth < 640 ? 10 : 11 },
                maxTicksLimit: 8,
                callback: (value) => shouldDisplayLogTick(value) ? formatCompactNumber(value) : ""
              },
              title: {
                display: true,
                text: "Ad count"
              }
            }
          }
        },
        plugins: [quadrantPlugin]
      });

      const topGap = [...data.occupations].sort((left, right) => (right.gap_ratio || 0) - (left.gap_ratio || 0)).slice(0, 5);
      const lowGap = [...data.occupations].sort((left, right) => (left.gap_ratio || 0) - (right.gap_ratio || 0)).slice(0, 5);
      const movers = Array.isArray(data.changes_vs_last_week)
        ? data.changes_vs_last_week.slice(0, 3)
        : [...data.occupations]
            .filter((entry) => Number.isFinite(entry.previous_gap_ratio))
            .map((entry) => ({ term: entry.term, change: (entry.gap_ratio || 0) - entry.previous_gap_ratio }))
            .sort((left, right) => Math.abs(right.change) - Math.abs(left.change))
            .slice(0, 3);

      document.getElementById("demand-gap-callouts").innerHTML = `
        <article class="callout-card">
          <p class="callout-label">Most overlooked by job seekers</p>
          <p class="callout-copy">${topGap.map((entry) => `${escapeHtml(entry.term)} (${Number(entry.gap_ratio || 0).toFixed(2)})`).join("<br>")}</p>
        </article>
        <article class="callout-card">
          <p class="callout-label">Most competitive to enter</p>
          <p class="callout-copy">${lowGap.map((entry) => `${escapeHtml(entry.term)} (${Number(entry.gap_ratio || 0).toFixed(2)})`).join("<br>")}</p>
        </article>
        <article class="callout-card">
          <p class="callout-label">This week vs last week</p>
          <p class="callout-copy">${movers.length
            ? movers.map((entry) => `${escapeHtml(entry.term)} (${(entry.change || 0) >= 0 ? "+" : ""}${Number(entry.change || 0).toFixed(2)})`).join("<br>")
            : "Week-over-week gap change is not available in this data file yet."}</p>
        </article>
      `;
    }

    function renderAdLifespanSection(container, data) {
      if (!Array.isArray(data?.occupation_fields) || !data.occupation_fields.length) {
        container.innerHTML = createPipelinePlaceholder();
        return;
      }

      // Sort by % still open > 60 days descending — that's where the real variation lives.
      // (14 of 18 sectors share the same 30-day median, so median alone isn't the story.)
      const fields = [...data.occupation_fields].sort(
        (a, b) => (Number(b.pct_open_over_60d) || 0) - (Number(a.pct_open_over_60d) || 0)
      );

      const fastest = [...fields].sort((a, b) => (Number(b.pct_filled_under_7d) || 0) - (Number(a.pct_filled_under_7d) || 0))[0];
      const slowest = fields[0];
      const longest = data.overall?.longest_running_ads || [];

      const rows = fields.map((field) => {
        const fast = Number(field.pct_filled_under_7d) || 0;
        const slow = Number(field.pct_open_over_60d) || 0;
        const normal = Math.max(0, 100 - fast - slow);
        const days = Number(field.median_lifespan_days) || 0;

        return `
          <div class="lifespan-row">
            <span class="lifespan-name">${escapeHtml(field.term)}</span>
            <div class="lifespan-bar-wrap">
              <div class="lifespan-bar" title="${escapeHtml(field.term)}: ${fast}% filled in < 7 days · ${normal.toFixed(1)}% filled in 7–60 days · ${slow}% still open > 60 days">
                <div class="lifespan-seg lifespan-seg--fast"  style="width:${fast}%"></div>
                <div class="lifespan-seg lifespan-seg--mid"   style="width:${normal}%"></div>
                <div class="lifespan-seg lifespan-seg--slow"  style="width:${slow}%"></div>
              </div>
            </div>
            <span class="lifespan-stat lifespan-stat--fast"  title="Filled in under 7 days">${fast}%</span>
            <span class="lifespan-stat lifespan-stat--days"  title="Median lifespan">${days}d</span>
            <span class="lifespan-stat lifespan-stat--slow"  title="Still open after 60 days">${slow}%</span>
          </div>
        `;
      }).join("");

      container.innerHTML = `
        <div class="callout-box" id="lifespan-primary-callout"></div>
        <div class="callout-box" id="lifespan-open-ads"></div>
        <div class="section-surface">
          <div class="lifespan-legend">
            <span class="lifespan-legend-item"><span class="lifespan-legend-dot lifespan-legend-dot--fast"></span>Filled &lt; 7 days</span>
            <span class="lifespan-legend-item"><span class="lifespan-legend-dot lifespan-legend-dot--mid"></span>Filled in 7–60 days</span>
            <span class="lifespan-legend-item"><span class="lifespan-legend-dot lifespan-legend-dot--slow"></span>Still open &gt; 60 days</span>
          </div>
          <div class="lifespan-header">
            <span>Sector</span>
            <span>Breakdown</span>
            <span class="lifespan-stat-label lifespan-stat-label--fast">&lt; 7d</span>
            <span class="lifespan-stat-label lifespan-stat-label--days">Median</span>
            <span class="lifespan-stat-label lifespan-stat-label--slow">&gt; 60d</span>
          </div>
          <div class="lifespan-table">${rows}</div>
        </div>
      `;

      document.getElementById("lifespan-primary-callout").innerHTML = `
        <p class="callout-label">Most striking pattern</p>
        <p class="callout-value">${escapeHtml(slowest.term)} is the hardest to fill — ${slowest.pct_open_over_60d}% of ads are still open after 60 days. ${escapeHtml(fastest.term)} fills fastest: ${fastest.pct_filled_under_7d}% of its ads close within a week.</p>
      `;

      document.getElementById("lifespan-open-ads").innerHTML = `
        <p class="callout-label">Longest-running live ads</p>
        <p class="callout-copy">${longest.length
          ? longest.map((entry) => `${escapeHtml(String(entry.headline || "").slice(0, 60))} · ${escapeHtml(entry.occupation_field || "—")} · ${escapeHtml(entry.region || "—")} · ${formatNumber(entry.days_open)} days`).join("<br>")
          : "No long-running live ads are listed in this data file yet."}</p>
      `;
    }

    function renderRegionalSplitSection(container, data) {
      if (!Array.isArray(data?.regions) || !data.regions.length) {
        container.innerHTML = createPipelinePlaceholder();
        return;
      }

      container.innerHTML = `
        <div class="section-surface">
          <div class="regional-controls">
            <label class="explorer-field">
              <span class="explorer-label">Region</span>
              <select class="explorer-select" id="regional-select"></select>
            </label>
          </div>
          <div class="regional-summary" id="regional-summary"></div>
          <div id="regional-split-table"></div>
          <div class="callout-grid" id="regional-split-callouts"></div>
          <div id="regional-history-table"></div>
        </div>
      `;

      const select = document.getElementById("regional-select");
      const defaultRegionId = "zdoY_6u5_Krt";
      let selectedRegionId = data.regions.find((region) => region.concept_id === defaultRegionId)?.concept_id || data.regions[0].concept_id;

      select.innerHTML = data.regions.map((region) => `
        <option value="${escapeHtml(region.concept_id)}" ${region.concept_id === selectedRegionId ? "selected" : ""}>${escapeHtml(region.term)}</option>
      `).join("");

      function buildRegionRows(entries, isOver) {
        // Scale bars relative to the max deviation in this direction.
        const maxDev = Math.max(...entries.map((e) => {
          const v = Number(e.vs_national) || 0;
          return isOver ? (v - 1) : (1 - v);
        }), 0.01);

        return entries.map((entry) => {
          const v = Number(entry.vs_national) || 0;
          const dev = isOver ? (v - 1) : (1 - v);
          const pct = Math.round(dev * 100);
          const barWidth = Math.round((dev / maxDev) * 100);
          const share = Math.round((Number(entry.regional_share) || 0) * 1000) / 10;
          const label = isOver ? `+${pct}%` : `−${pct}%`;
          const color = isOver ? "#006a61" : "#b45309";
          const title = `${entry.term}: ${label} vs national average · ${share}% of region's ads`;

          return `
            <div class="rsplit-row">
              <span class="rsplit-name">${escapeHtml(entry.term)}</span>
              <div class="rsplit-bar-wrap" title="${escapeHtml(title)}">
                <div class="rsplit-bar" style="width:${barWidth}%;background:${color}"></div>
              </div>
              <span class="rsplit-dev" style="color:${color}">${escapeHtml(label)}</span>
              <span class="rsplit-share">${share}%</span>
            </div>
          `;
        }).join("");
      }

      function render() {
        selectedRegionId = select.value;
        const region = data.regions.find((item) => item.concept_id === selectedRegionId) || data.regions[0];
        const nationalTotal = data.regions.reduce((sum, item) => sum + (Number(item.total_ads) || 0), 0);
        const share = nationalTotal ? (Number(region.total_ads) / nationalTotal) * 100 : 0;

        document.getElementById("regional-summary").innerHTML = `
          <article class="stat-card">
            <p class="stat-label">Total ads this week</p>
            <p class="stat-value">${formatNumber(region.total_ads)}</p>
          </article>
          <article class="stat-card">
            <p class="stat-label">Share of national total</p>
            <p class="stat-value">${formatPercent(share)}</p>
          </article>
        `;

        const fields = [...(region.occupation_fields || [])]
          .filter((e) => e.term && e.term !== "Default");

        const overrep = fields
          .filter((e) => (Number(e.vs_national) || 0) > 1)
          .sort((a, b) => (Number(b.vs_national) || 0) - (Number(a.vs_national) || 0));

        const underrep = fields
          .filter((e) => (Number(e.vs_national) || 0) < 1)
          .sort((a, b) => (Number(a.vs_national) || 0) - (Number(b.vs_national) || 0));

        const colHeaders = `
          <div class="rsplit-header">
            <span>Sector</span>
            <span>Deviation from national avg</span>
            <span class="rsplit-dev-label">vs avg</span>
            <span class="rsplit-share-label">of ads</span>
          </div>
        `;

        const overSection = overrep.length ? `
          <p class="rsplit-section-label rsplit-section-label--over">More active than national average</p>
          ${colHeaders}
          <div class="rsplit-rows">${buildRegionRows(overrep, true)}</div>
        ` : "";

        const underSection = underrep.length ? `
          <p class="rsplit-section-label rsplit-section-label--under">Less active than national average</p>
          ${colHeaders}
          <div class="rsplit-rows">${buildRegionRows(underrep, false)}</div>
        ` : "";

        document.getElementById("regional-split-table").innerHTML = `
          <div class="rsplit-table">${overSection}${underSection}</div>
        `;

        const top1 = overrep[0];
        const bot1 = underrep[0];
        document.getElementById("regional-split-callouts").innerHTML = `
          <article class="callout-card">
            <p class="callout-label">Most specialized in</p>
            <p class="callout-copy">${top1
              ? `${escapeHtml(top1.term)} is ${Math.round(((Number(top1.vs_national) || 0) - 1) * 100)}% above the national average share.`
              : "No sectors are over-represented in this region."}</p>
          </article>
          <article class="callout-card">
            <p class="callout-label">Most underrepresented</p>
            <p class="callout-copy">${bot1
              ? `${escapeHtml(bot1.term)} is ${Math.round((1 - (Number(bot1.vs_national) || 0)) * 100)}% below the national average share.`
              : "No sectors are under-represented in this region."}</p>
          </article>
          <article class="callout-card">
            <p class="callout-label">Pattern stability</p>
            <p class="callout-copy">${Array.isArray(region.recent_weeks) || Array.isArray(data.recent_weeks)
              ? "Recent weekly comparison is available below."
              : "Historical regional comparison is not included in this data file yet."}</p>
          </article>
        `;

        const recentWeeks = region.recent_weeks || data.recent_weeks?.[region.concept_id] || [];
        const historyContainer = document.getElementById("regional-history-table");
        if (!Array.isArray(recentWeeks) || !recentWeeks.length) {
          historyContainer.innerHTML = '<p class="section-note">Historical regional comparison is not available yet.</p>';
          return;
        }

        historyContainer.innerHTML = `
          <table class="comparison-table">
            <thead>
              <tr>
                <th>Week</th>
                <th>Total ads</th>
                <th>Top specialized field</th>
                <th>vs national</th>
              </tr>
            </thead>
            <tbody>
              ${recentWeeks.map((week) => `
                <tr>
                  <td>${escapeHtml(week.week || "—")}</td>
                  <td>${formatNumber(week.total_ads || 0)}</td>
                  <td>${escapeHtml(week.top_field?.term || "—")}</td>
                  <td>${week.top_field ? `${(((week.top_field.vs_national || 0) - 1) * 100).toFixed(0)}%` : "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        `;
      }

      select.addEventListener("change", render);
      render();
    }

    function initSectionNavigation() {
      const links = Array.from(document.querySelectorAll(".section-nav-link"));
      const sections = Array.from(document.querySelectorAll(".nav-target"));

      links.forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          const target = document.querySelector(link.getAttribute("href"));
          if (!target) return;
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });

      const observer = new IntersectionObserver((entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        if (!visible) return;
        links.forEach((link) => {
          link.classList.toggle("is-active", link.getAttribute("href") === `#${visible.target.id}`);
        });
      }, {
        rootMargin: "-20% 0px -55% 0px",
        threshold: [0.1, 0.25, 0.5]
      });

      sections.forEach((section) => observer.observe(section));
      links[0]?.classList.add("is-active");
    }

    async function init() {
      const [
        live,
        history,
        meta,
        occupationDecay,
        skillVelocity,
        demandGap,
        adLifespan,
        regionalSplit
      ] = await Promise.all([
        fetchLocalJson("data/live.json"),
        fetchLocalJson("data/history.json"),
        fetchLocalJson("data/meta.json"),
        fetchLocalJson("data/occupation_decay.json"),
        fetchLocalJson("data/skill_velocity.json"),
        fetchLocalJson("data/demand_gap.json"),
        fetchLocalJson("data/ad_lifespan.json"),
        fetchLocalJson("data/regional_split.json")
      ]);

      liveData = live || SAMPLE_LIVE;
      // Preserve an empty array when history.json loads but contains zero entries,
      // so the launch-state (zero-entry) path can show the correct notice.
      historyData = Array.isArray(history) ? history : (history === null ? SAMPLE_HISTORY : []);
      metaData = meta || SAMPLE_META;

      if (!live || !meta) {
        showErrorOverlay();
        window.setTimeout(() => document.getElementById("error-overlay").classList.add("hidden"), 2400);
      }

      renderLivePulseSection();
      renderOptionalSections({
        occupationDecay,
        skillVelocity,
        demandGap,
        adLifespan,
        regionalSplit
      });

      initSectionNavigation();
      hideLoading();
    }

    document.getElementById("timeframe-selector").addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button || button.disabled) return;
      setActiveTimeframeButton(button);
      currentWeeks = Number(button.dataset.weeks);
      updateTimeframeCharts();
    });

    window.addEventListener("resize", () => {
      if (liveData) {
        renderLivePulseStaticCharts();
        updateTimeframeCharts();
      }
    });

    window.addEventListener("DOMContentLoaded", () => {
      init().catch((error) => {
        console.error("Dashboard initialisation failed", error);
        showErrorOverlay();
        hideLoading();
      });
    });
