    // Swedish Job Pulse — Career Reality Check
    // Static-first: reads data/career_reality.json and turns the user's
    // situation into practical, blunt career advice. No charts, no backend.

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
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

    // =====================================================================
    // Career Reality Check
    // A blunt, practical matcher over data/career_reality.json. The heavy
    // signal work (ML forecast + scoring) happens offline in the Python
    // layer; here we only turn the user's situation into concrete advice.
    // =====================================================================
    let careerRealityData = null;

    // Experience area -> primary occupation field id(s) used for ranking.
    const CRC_EXPERIENCE_FIELDS = {
      customer_service: "X82t_awd_Qyc",
      sales: "RPTn_bxG_ExZ",
      admin: "X82t_awd_Qyc",
      it: "apaJ_2ja_LuF",
      healthcare: "NYW6_mP6_vwf",
      education: "MVqp_eS8_kDZ",
      restaurant: "ScKy_FHB_7wT",
      logistics: "ASGV_zcE_bWf",
      none: null
    };

    // Free-text target -> occupation field. Ordered: first hit wins, so
    // Data/IT comes before Admin (so "data analyst" maps to IT, not admin).
    const CRC_TARGET_ALIASES = [
      { field: "apaJ_2ja_LuF", kw: ["develop", "utveckl", "software", "mjukvar", "programmer", "devops", "data analyst", "dataanalyt", "data scientist", "data engineer", "dataingenjör", "business intelligence", "bi developer", "frontend", "backend", "fullstack", "it-säkerhet", "cyber", "systemutveckl", "webb"] },
      { field: "NYW6_mP6_vwf", kw: ["nurse", "sjukskötersk", "undersköter", "läkare", "doctor", "vårdbiträd", "physician", "tandläk", "barnmorsk"] },
      { field: "GazW_2TU_kJw", kw: ["social worker", "socialsekret", "boendestöd", "behandlingsassist", "personlig assistent", "personal assistant", "socialpedagog", "fritidsled"] },
      { field: "MVqp_eS8_kDZ", kw: ["teacher", "lärare", "förskoll", "pedagog", "barnskötare", "teaching"] },
      { field: "RPTn_bxG_ExZ", kw: ["sales", "säljare", "account manager", "marketing", "marknadsför", "retail", "butikssälj", "key account"] },
      { field: "ScKy_FHB_7wT", kw: ["chef", "kock", "waiter", "servit", "restaurant", "restaurang", "barista", "kitchen", "kök", "bartender"] },
      { field: "ASGV_zcE_bWf", kw: ["warehouse", "lager", "logistic", "logistik", "driver", "chaufför", "truck", "lastbil", "terminal"] },
      { field: "6Hq3_tKo_V57", kw: ["engineer", "ingenjör", "civilingenjör"] },
      { field: "j7Cq_ZJe_GkT", kw: ["construction", "bygg", "snickare", "carpenter"] },
      { field: "yhCP_AqT_tns", kw: ["mechanic", "mekaniker", "electric", "elektriker", "maintenance", "underhåll", "fastighetsskötare"] },
      { field: "wTEr_CBC_bqh", kw: ["operator", "maskinoperatör", "industri", "welder", "svetsare", "montör"] },
      { field: "whao_Q6A_ScE", kw: ["clean", "städ", "lokalvård"] },
      { field: "E7hm_BLq_fqZ", kw: ["security", "väktare", "bevakning"] },
      { field: "X82t_awd_Qyc", kw: ["admin", "ekonom", "economy", "accountant", "controller", "human resources", "receptionist", "kundtjänst", "customer service", "customer support", "analyst", "analytiker", "reporting", "rapporter", "coordinator", "koordinator", "handläggare", "utredare", "planerare"] }
    ];

    // Common user wording -> closest occupation-group label in JobTech data.
    // These run before field-level aliases so evidence can anchor on a closer
    // occupation when the public taxonomy has a clear match.
    const CRC_TARGET_ROLE_ALIASES = [
      { term: "Kundtjänstpersonal", kw: ["customer service", "customer support", "kundtjänst", "kundsupport"] },
      { term: "Lager- och terminalpersonal", kw: ["warehouse", "lager", "warehouse worker"] },
      { term: "Lastbilsförare", kw: ["truck driver", "lastbilsförare", "lastbilsför", "chaufför"] },
      { term: "Mjukvaru- och systemutvecklare", kw: ["software developer", "system developer", "systemutvecklare", "mjukvaruutvecklare"] },
      { term: "Grundutbildade sjuksköterskor", kw: ["nurse", "sjuksköterska", "registered nurse"] },
      { term: "Grundskollärare", kw: ["teacher", "lärare", "school teacher"] },
      { term: "Butikssäljare", kw: ["sales", "säljare", "retail sales"] }
    ];

    // Fields where roles usually expect working Swedish (customer/colleague
    // facing). English-only candidates get a penalty here unless the field is
    // English-tolerant (tech) or the role has a strong remote signal.
    const CRC_LANGUAGE_HEAVY = new Set([
      "NYW6_mP6_vwf", "GazW_2TU_kJw", "MVqp_eS8_kDZ", "X82t_awd_Qyc",
      "RPTn_bxG_ExZ", "ScKy_FHB_7wT", "Uuf1_GMh_Uvw"
    ]);
    const CRC_ENGLISH_OK = new Set(["apaJ_2ja_LuF", "6Hq3_tKo_V57", "kJeN_wmw_9wX"]);

    const CRC_STUDY_TIER = { none: 0, short: 1, mid: 2, long: 3 };

    function crcNorm(value) {
      return String(value || "").toLowerCase().trim();
    }

    function crcGetOccupations() {
      return Array.isArray(careerRealityData?.occupations) ? careerRealityData.occupations : [];
    }

    function crcMatchOccupation(name) {
      const n = crcNorm(name);
      if (n.length < 3) return null;
      let best = null;
      let bestLen = 0;
      crcGetOccupations().forEach((occ) => {
        const term = crcNorm(occ.term);
        if (!term) return;
        if (term.includes(n) || n.includes(term)) {
          const overlap = Math.min(term.length, n.length);
          if (overlap > bestLen) { best = occ; bestLen = overlap; }
        }
      });
      return best;
    }

    function crcFieldFromAlias(targetText) {
      const t = crcNorm(targetText);
      if (!t) return null;
      for (const entry of CRC_TARGET_ALIASES) {
        if (entry.kw.some((kw) => t.includes(kw))) return entry.field;
      }
      return null;
    }

    function crcOccupationFromRoleAlias(targetText) {
      const t = crcNorm(targetText);
      if (!t) return null;
      for (const entry of CRC_TARGET_ROLE_ALIASES) {
        if (!entry.kw.some((kw) => t.includes(kw))) continue;
        const termNeedle = crcNorm(entry.term);
        const hit = crcGetOccupations().find((occ) => crcNorm(occ.term).includes(termNeedle));
        if (hit) return hit;
      }
      return null;
    }

    function crcTopOccupationInField(fieldId) {
      if (!fieldId) return null;
      const inField = crcGetOccupations().filter((occ) => occ.field_id === fieldId);
      if (!inField.length) return null;
      // Prefer the strongest occupation that actually has a demand forecast, so
      // the "Why this verdict?" panel can show the ML signal rather than a gap.
      const withForecast = inField.filter((occ) => occ.forecast);
      const pool = withForecast.length ? withForecast : inField;
      return pool.reduce((best, occ) =>
        (!best || occ.opportunity_score > best.opportunity_score) ? occ : best, null);
    }

    // Stem-aware word match so Swedish singular/plural forms line up
    // (e.g. "undersköterska" matches the occupation "Undersköterskor ...").
    function crcStemMatch(termWord, token) {
      if (termWord === token) return true;
      if (token.length < 6 || termWord.length < 6) return false;
      const shorter = token.length <= termWord.length ? token : termWord;
      const longer = shorter === token ? termWord : token;
      return longer.startsWith(shorter.slice(0, Math.max(6, shorter.length - 2)));
    }

    function crcFindAnchor(targetText) {
      // 1) direct token/substring match against occupation terms
      const direct = crcMatchOccupation(targetText);
      if (direct) return { occ: direct, viaAlias: false };
      // 2) curated common phrase -> occupation-group aliases
      const roleAlias = crcOccupationFromRoleAlias(targetText);
      if (roleAlias) return { occ: roleAlias, viaAlias: true, fieldId: roleAlias.field_id };
      // 3) stem-aware token overlap (handle multi-word free text + word forms)
      const tokens = crcNorm(targetText).split(/[^a-zåäö0-9]+/).filter((w) => w.length >= 4);
      if (tokens.length) {
        let best = null;
        let bestScore = 0;
        crcGetOccupations().forEach((occ) => {
          const termWords = crcNorm(occ.term).split(/[^a-zåäö0-9]+/).filter((w) => w.length >= 4);
          const hits = tokens.filter((tok) => termWords.some((tw) => crcStemMatch(tw, tok))).length;
          if (hits > bestScore) { best = occ; bestScore = hits; }
        });
        if (best && bestScore > 0) return { occ: best, viaAlias: false };
      }
      // 4) alias -> field -> strongest occupation in that field
      const fieldId = crcFieldFromAlias(targetText);
      if (fieldId) {
        const occ = crcTopOccupationInField(fieldId);
        if (occ) return { occ, viaAlias: true, fieldId };
      }
      return null;
    }

    function crcGetPath(experience) {
      const paths = Array.isArray(careerRealityData?.career_paths) ? careerRealityData.career_paths : [];
      return paths.find((p) => p.experience_key === experience)
        || paths.find((p) => p.experience_key === "none")
        || paths[0] || null;
    }

    function crcRegionDelta(fieldId, region) {
      if (!fieldId || !region) return 0;
      const info = careerRealityData?.regional_field_strength?.[region]?.[fieldId];
      if (!info) return 0;
      return { strong: 6, medium: 0, weak: -6 }[info.signal] || 0;
    }

    function crcRegionSignal(fieldId, region) {
      if (!fieldId || !region) return null;
      return careerRealityData?.regional_field_strength?.[region]?.[fieldId]?.signal || null;
    }

    // Score an occupation for this specific user (region + language + remote).
    function crcUserScore(occ, inputs) {
      if (!occ) return 0;
      let score = Number(occ.opportunity_score) || 0;
      score += crcRegionDelta(occ.field_id, inputs.region);
      const heavy = CRC_LANGUAGE_HEAVY.has(occ.field_id);
      const englishOk = CRC_ENGLISH_OK.has(occ.field_id) || occ.remote_signal === "strong";
      if (inputs.swedish === "english" && heavy && !englishOk) score -= 16;
      else if (inputs.swedish === "basic" && heavy && !englishOk) score -= 7;
      if (inputs.remote === "important") {
        if (occ.remote_signal === "strong") score += 5;
        else if (occ.remote_signal === "weak" || occ.remote_signal === "unknown") score -= 5;
      }
      return Math.max(0, Math.min(100, Math.round(score)));
    }

    function crcDecideVerdict(anchor, inputs) {
      const tier = CRC_STUDY_TIER[inputs.study] ?? 0;
      if (!anchor) {
        if (inputs.experience === "none" && !inputs.skills.length) return "unknown";
        return "now";
      }
      const occ = anchor.occ;
      const score = crcUserScore(occ, inputs);
      const entryBlock = inputs.level === "entry" && occ.entry_level_signal === "weak";
      const crowdHigh = occ.crowding_risk === "high";
      let key;
      if (occ.demand_level === "low" && crowdHigh) key = "risky";
      else if (entryBlock && crowdHigh) key = tier >= 2 ? "soon" : "risky";
      else if (entryBlock) key = "soon";
      else if (score >= 62) key = "now";
      else if (score >= 46 || tier >= 1) key = "soon";
      else key = "risky";
      // The exact target wasn't found — we only matched the field. Don't tell a
      // non-experienced user a specific unconfirmed role is realistic "now".
      if (anchor.viaAlias && key === "now" && inputs.level !== "experienced") key = "soon";
      return key;
    }

    function crcRoleObject(name, bucket, inputs) {
      const occ = crcMatchOccupation(name);
      const tagByBucket = { now: "Apply now", reach: "Prepare first", risk: "Avoid for now" };
      const obj = { name, tag: tagByBucket[bucket], occ };
      if (occ) obj.score = crcUserScore(occ, inputs);
      return obj;
    }

    function crcBuildBuckets(path, anchor, inputs, verdictKey) {
      const tier = CRC_STUDY_TIER[inputs.study] ?? 0;
      let now = [...(path?.realistic_now_roles || [])];
      let reach = [...(path?.reachable_roles || [])];
      let risk = [...(path?.risky_roles || [])];

      // Study willingness reshapes the reachable / risky boundary.
      if (tier === 0) {
        reach = reach.slice(0, 2);            // stay close to current experience
      } else if (tier >= 2) {
        // Allow more ambitious transitions, but keep at least one role in the
        // "risky / crowded" column so the warning bucket is never empty.
        const pull = Math.min(tier === 3 ? 2 : 1, Math.max(0, risk.length - 1));
        reach = reach.concat(risk.slice(0, pull));
        risk = risk.slice(pull);
      }

      // Experienced candidates can treat the first reachable role as realistic.
      if (inputs.level === "experienced" && reach.length) {
        now = [reach.shift(), ...now];
      }

      // Place the named target in the bucket that matches its verdict.
      if (anchor && !anchor.viaAlias) {
        const target = anchor.occ.term;
        if (verdictKey === "now") now = [target, ...now];
        else if (verdictKey === "soon") reach = [target, ...reach];
        else if (verdictKey === "risky") risk = [target, ...risk];
      }

      const seen = new Set();
      const take = (list, bucket) => {
        const out = [];
        for (const name of list) {
          const key = crcNorm(name);
          if (!key || seen.has(key)) continue;
          seen.add(key);
          const role = crcRoleObject(name, bucket, inputs);
          // English-only: push language-heavy "now" roles down to "prepare".
          if (bucket === "now" && inputs.swedish === "english" && role.occ
              && CRC_LANGUAGE_HEAVY.has(role.occ.field_id)
              && !CRC_ENGLISH_OK.has(role.occ.field_id)
              && role.occ.remote_signal !== "strong") {
            continue; // handled by reach below
          }
          out.push(role);
          if (out.length >= 5) break;
        }
        return out;
      };

      const nowRoles = take(now, "now");
      // Re-add the language-skipped roles into reach for english-only users.
      if (inputs.swedish === "english") {
        now.forEach((name) => {
          const key = crcNorm(name);
          const occ = crcMatchOccupation(name);
          if (occ && CRC_LANGUAGE_HEAVY.has(occ.field_id) && !CRC_ENGLISH_OK.has(occ.field_id)
              && occ.remote_signal !== "strong" && !seen.has(key)) {
            reach.push(name);
          }
        });
      }
      const reachRoles = take(reach, "reach");
      const riskRoles = take(risk, "risk");

      // Backfill "realistic now" from the strongest occupations in the user's
      // experience field if the curated list came up short.
      if (nowRoles.length < 3) {
        const fieldId = CRC_EXPERIENCE_FIELDS[inputs.experience];
        crcGetOccupations()
          .filter((o) => (!fieldId || o.field_id === fieldId) && o.demand_level !== "low")
          .sort((a, b) => crcUserScore(b, inputs) - crcUserScore(a, inputs))
          .forEach((o) => {
            const key = crcNorm(o.term);
            if (nowRoles.length >= 3 || seen.has(key)) return;
            seen.add(key);
            nowRoles.push(crcRoleObject(o.term, "now", inputs));
          });
      }

      return { now: nowRoles, reach: reachRoles, risk: riskRoles };
    }

    function crcBuildSkills(path, anchor, inputs) {
      const have = new Set(inputs.skills.map(crcNorm));
      const out = [];
      const seen = new Set();
      const push = (skill, growing) => {
        const key = crcNorm(skill);
        if (!key || seen.has(key) || have.has(key)) return;
        seen.add(key);
        out.push({ skill, growing: !!growing });
      };
      // Growing, field-relevant skills from the anchor first (highest signal).
      (anchor?.occ?.related_skills || []).forEach((s) => {
        if (s.signal === "growing") push(s.skill, true);
      });
      (path?.skills_to_add || []).forEach((s) => push(s, false));
      (anchor?.occ?.related_skills || []).forEach((s) => {
        if (s.signal !== "growing") push(s.skill, false);
      });
      return out.slice(0, 6);
    }

    function crcBuildKeywords(path, anchor, buckets) {
      const out = [];
      const seen = new Set();
      const push = (kw) => {
        const key = crcNorm(kw);
        if (!key || seen.has(key)) return;
        seen.add(key);
        out.push(kw);
      };
      if (anchor && !anchor.viaAlias) push(anchor.occ.term);
      buckets.now.slice(0, 2).forEach((r) => push(r.name));
      (path?.search_keywords?.sv || []).forEach(push);
      (path?.search_keywords?.en || []).forEach(push);
      return out.slice(0, 9);
    }

    function crcCapitalize(value) {
      const s = String(value || "");
      return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
    }

    // User-provided skills that actually appear in the market data — proof that
    // the candidate already holds in-demand skills.
    function crcMatchedSkills(anchor, inputs) {
      const dataSkills = Array.isArray(careerRealityData?.skills) ? careerRealityData.skills : [];
      const related = anchor?.occ?.related_skills || [];
      const matched = [];
      inputs.skills.forEach((raw) => {
        const u = crcNorm(raw);
        if (u.length < 2) return;
        const hit = dataSkills.find((s) => {
          const t = crcNorm(s.term);
          return t && (t.includes(u) || u.includes(t));
        });
        const rel = related.find((s) => {
          const t = crcNorm(s.skill);
          return t && (t.includes(u) || u.includes(t));
        });
        if (hit || rel) {
          matched.push({ skill: raw, signal: (hit && hit.signal) || (rel && rel.signal) || null });
        }
      });
      return matched.slice(0, 3);
    }

    // The "Why this verdict?" evidence rows — the signals behind the call.
    function crcBuildEvidence(occ, inputs, matchedSkills) {
      const rows = [];
      if (occ) {
        const trendTone = { rising: "good", declining: "bad", stable: "", unknown: "" };
        const arrow = { rising: "↗", declining: "↘", stable: "→", unknown: "" };
        rows.push({
          label: "Demand trend",
          value: `${crcCapitalize(occ.demand_trend)} ${arrow[occ.demand_trend] || ""}`.trim(),
          tone: trendTone[occ.demand_trend] || ""
        });

        // ML / baseline forecast direction + magnitude where available.
        if (occ.forecast && occ.forecast.source && occ.forecast.source !== "none") {
          const pct = Number(occ.forecast.pct_change);
          const horizon = occ.forecast.horizon_weeks || 4;
          const src = occ.forecast.source === "ml" ? "ML" : "baseline";
          let value;
          if (Number.isFinite(pct)) {
            const signed = `${pct >= 0 ? "+" : ""}${Math.round(pct * 100)}%`;
            value = `${signed} over next ${horizon} wks (${src})`;
          } else {
            value = `${crcCapitalize(occ.forecast.trend_class)} (${src})`;
          }
          const fTone = occ.forecast.trend_class === "grow" ? "good"
            : (occ.forecast.trend_class === "decline" ? "bad" : "");
          rows.push({ label: "Forecast", value, tone: fTone });
        }

        const crowdTone = { high: "bad", medium: "warn", low: "good", unknown: "" };
        rows.push({ label: "Crowding risk", value: crcCapitalize(occ.crowding_risk), tone: crowdTone[occ.crowding_risk] || "" });

        const entryTone = { strong: "good", medium: "", weak: "bad", unknown: "" };
        rows.push({ label: "Entry-level signal", value: crcCapitalize(occ.entry_level_signal), tone: entryTone[occ.entry_level_signal] || "" });

        const remoteTone = { strong: "good", medium: "", weak: "warn", unknown: "" };
        rows.push({ label: "Remote signal", value: crcCapitalize(occ.remote_signal), tone: remoteTone[occ.remote_signal] || "" });

        // Regional fit (only when a specific region is chosen).
        if (inputs.region) {
          const sig = crcRegionSignal(occ.field_id, inputs.region);
          if (sig) {
            const map = { strong: "good", medium: "", weak: "bad" };
            rows.push({ label: "Regional fit", value: `${crcCapitalize(sig)} in ${inputs.region}`, tone: map[sig] || "" });
          }
        }
      }

      if (matchedSkills && matchedSkills.length) {
        const names = matchedSkills.map((m) => m.skill).join(", ");
        rows.push({ label: "Your matched skills", value: names, tone: "good" });
      }
      return rows;
    }

    function crcComposeVerdictText(key, anchor, inputs, buckets, skills) {
      const occ = anchor?.occ;
      // Echo the user's own wording where they gave one; fall back to the term.
      const target = inputs.targetRaw.trim() || (occ ? occ.term : null);
      const altRoles = (buckets.reach.length ? buckets.reach : buckets.now)
        .slice(0, 3).map((r) => r.name);
      const topSkills = skills.slice(0, 2).map((s) => s.skill);
      const region = inputs.region;
      const parts = [];

      const regionNote = () => {
        if (!occ || !region) return "";
        const sig = crcRegionSignal(occ.field_id, region);
        if (sig === "strong") return ` ${region} is a strong region for this field.`;
        if (sig === "weak") return ` In ${region}, this field is under-weighted, so expect fewer local openings.`;
        return "";
      };
      const forecastNote = () => {
        if (!occ?.forecast || occ.forecast.source === "none") return "";
        if (occ.demand_trend === "rising") return " The 4-week forecast points up for this area.";
        if (occ.demand_trend === "declining") return " The 4-week forecast points down for this area, so move quickly.";
        return "";
      };

      if (key === "now") {
        if (target) parts.push(`${target} is a realistic target right now.`);
        else parts.push("Based on your experience, you have realistic options right now.");
        if (occ) parts.push(occ.consultant_summary);
        parts.push("Apply now — but spread applications across the realistic-now roles below, don't sit on a single title." + regionNote() + forecastNote());
      } else if (key === "soon") {
        if (target) parts.push(`${target} is reachable, but not as your first step.`);
        else parts.push("This direction is reachable, but not as your first step.");
        if (anchor?.viaAlias && occ?.field_label) parts.push(`(We matched it to the ${occ.field_label} field — name an exact role for a sharper read.)`);
        const why = occ
          ? (occ.crowding_risk === "high"
              ? "The market signal is competitive"
              : (occ.entry_level_signal === "weak" ? "Entry-level access looks limited" : "The current fit is only moderate"))
          : "The current signal is mixed";
        let line = `${why}. Start with ${altRoles.slice(0, 3).join(", ") || "the realistic-now roles below"}`;
        if (topSkills.length) line += ` while adding ${topSkills.join(" and ")}`;
        parts.push(line + "." + regionNote() + forecastNote());
      } else if (key === "risky") {
        if (target) parts.push(`${target} is a crowded or weak-entry path for you right now.`);
        else parts.push("This is a crowded or weak-entry path for you right now.");
        parts.push(`Apply to the realistic-now roles instead${altRoles.length ? ` (${altRoles.slice(0, 2).join(", ")})` : ""} and prepare before targeting it.` + regionNote());
      } else {
        parts.push("Not enough signal to judge a specific target. Start with the entry-friendly, high-volume roles below, and add a target job for a sharper read.");
      }
      return parts.filter(Boolean).join(" ");
    }

    function crcBuildCaution(anchor, inputs) {
      const occ = anchor?.occ;
      if (!occ) return null;
      const heavy = CRC_LANGUAGE_HEAVY.has(occ.field_id);
      const englishOk = CRC_ENGLISH_OK.has(occ.field_id) || occ.remote_signal === "strong";
      if (inputs.swedish === "english" && heavy && !englishOk) {
        return `English-only is a real barrier for ${occ.field_label || "these"} roles in Sweden — most expect working Swedish. Prioritise English-tolerant or remote roles, or plan Swedish study before you commit.`;
      }
      if (inputs.level === "entry" && occ.entry_level_signal === "weak") {
        return occ.caution || "Entry-level access looks limited compared with total demand. Get a nearby role first.";
      }
      if (occ.caution) return occ.caution;
      return null;
    }

    function crcBuildPlan(buckets, skills, inputs, anchor) {
      const nowNames = buckets.now.slice(0, 3).map((r) => r.name);
      const reachNames = buckets.reach.slice(0, 2).map((r) => r.name);
      const riskNames = buckets.risk.slice(0, 2).map((r) => r.name);
      const learn = skills.slice(0, 3).map((s) => s.skill);
      const cvBits = [];
      const expLabel = {
        customer_service: "customer communication", sales: "sales and pipeline",
        admin: "coordination and reporting", it: "your technical stack",
        healthcare: "patient care", education: "teaching and group leadership",
        restaurant: "service and pace", logistics: "operations and accuracy",
        none: "reliability and availability"
      }[inputs.experience];
      if (expLabel) cvBits.push(expLabel);
      learn.slice(0, 2).forEach((s) => cvBits.push(s));

      const items = [];
      items.push(`Apply to ${Math.max(6, nowNames.length * 2)} realistic-now roles${nowNames.length ? ` — e.g. ${nowNames.join(", ")}` : ""}.`);
      if (reachNames.length) items.push(`Send ${reachNames.length >= 2 ? 4 : 3} applications to reachable roles — e.g. ${reachNames.join(", ")}.`);
      if (cvBits.length) items.push(`Rewrite your CV around ${cvBits.join(", ")}.`);
      if (learn.length) items.push(`Start learning ${learn.join(" and ")} this week.`);
      if (riskNames.length) items.push(`Avoid ${riskNames.join(" and ")} for now — revisit once you have stronger proof.`);
      return items;
    }

    function crcChipClass(bucket) {
      return { now: "crc-chip--go", reach: "crc-chip--prep", risk: "crc-chip--risk" }[bucket] || "";
    }

    function crcRenderBucket(title, note, modifier, roles, chipBucket) {
      const items = roles.length
        ? roles.map((r) => `
            <li class="crc-role">
              ${Number.isFinite(r.score) ? `<span class="crc-chip ${crcChipClass(chipBucket)}">${r.score}</span>` : ""}
              <span class="crc-role-name">${escapeHtml(r.name)}</span>
              <span class="crc-role-tag">${escapeHtml(r.tag)}</span>
            </li>`).join("")
        : `<li class="crc-empty">No clear roles in this bucket for your inputs.</li>`;
      return `
        <div class="crc-bucket crc-bucket--${modifier}">
          <div class="crc-bucket-head">${escapeHtml(title)}<span>${escapeHtml(note)}</span></div>
          <ul class="crc-bucket-list">${items}</ul>
        </div>`;
    }

    function crcRenderResult(model) {
      const container = document.getElementById("crc-results");
      if (!container) return;

      const verdictTitles = {
        now: "Realistic now", soon: "Reachable in 3–6 months",
        risky: "Risky for now", unknown: "Not enough signal"
      };
      const verdictMod = { now: "now", soon: "soon", risky: "risky", unknown: "unknown" }[model.verdictKey];
      const stamp = { now: "Apply now", soon: "Prepare first", risky: "Avoid for now", unknown: "Tell us more" }[model.verdictKey];

      const evidenceHtml = model.evidence.length ? `
        <div class="crc-panel crc-evidence">
          <p class="crc-panel-label">Why this verdict?${model.anchorTerm ? ` <span class="crc-evidence-sub">based on ${escapeHtml(model.anchorTerm)}</span>` : ""}</p>
          <div class="crc-evidence-list">
            ${model.evidence.map((r) => `<div class="crc-ev-row"><span class="crc-ev-label">${escapeHtml(r.label)}</span><span class="crc-ev-value${r.tone ? ` crc-ev-value--${r.tone}` : ""}">${escapeHtml(r.value)}</span></div>`).join("")}
          </div>
        </div>` : "";

      const skillsHtml = `
        <div class="crc-panel">
          <p class="crc-panel-label">Skills to add</p>
          <div class="crc-tags">
            ${model.skills.length
              ? model.skills.map((s) => `<span class="crc-tag${s.growing ? " crc-tag--grow" : ""}">${s.growing ? '<span class="crc-tag-dot"></span>' : ""}${escapeHtml(s.skill)}</span>`).join("")
              : '<span class="crc-empty">No extra skills flagged.</span>'}
          </div>
        </div>`;

      const keywordsHtml = `
        <div class="crc-panel">
          <p class="crc-panel-label">Best search keywords</p>
          <div class="crc-tags">
            ${model.keywords.map((k) => `<span class="crc-tag">${escapeHtml(k)}</span>`).join("")}
          </div>
        </div>`;

      const planHtml = `
        <div class="crc-panel crc-plan">
          <p class="crc-panel-label">Your 2-week action plan</p>
          <ul class="crc-plan-list">
            ${model.plan.map((item, i) => `<li class="crc-plan-item"><span class="crc-plan-num">${i + 1}</span><span>${escapeHtml(item)}</span></li>`).join("")}
          </ul>
        </div>`;

      const cautionHtml = model.caution ? `
        <div class="crc-caution">
          <p class="crc-caution-label">Caution</p>
          <p class="crc-caution-text">${escapeHtml(model.caution)}</p>
        </div>` : "";

      container.innerHTML = `
        <div class="crc-verdict crc-verdict--${verdictMod}">
          <span class="crc-verdict-stamp">${escapeHtml(stamp)}</span>
          <div class="crc-verdict-body">
            <h3 class="crc-verdict-title">${escapeHtml(verdictTitles[model.verdictKey])}</h3>
            <p class="crc-verdict-text">${escapeHtml(model.verdictText)}</p>
          </div>
        </div>
        ${evidenceHtml}
        <div class="crc-buckets">
          ${crcRenderBucket("Realistic now", "apply", "now", model.buckets.now, "now")}
          ${crcRenderBucket("Reachable with upgrades", "prepare", "reach", model.buckets.reach, "reach")}
          ${crcRenderBucket("Risky / crowded", "avoid for now", "risk", model.buckets.risk, "risk")}
        </div>
        <div class="crc-cols">
          ${skillsHtml}
          ${keywordsHtml}
        </div>
        ${planHtml}
        ${cautionHtml}`;

      container.hidden = false;
    }

    function crcReadInputs() {
      const val = (id) => document.getElementById(id)?.value || "";
      const radio = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value || "";
      const skills = val("crc-skills").split(",").map((s) => s.trim()).filter(Boolean);
      return {
        region: val("crc-region"),
        swedish: val("crc-swedish"),
        experience: val("crc-experience"),
        targetRaw: val("crc-target"),
        skills,
        level: radio("level"),
        remote: radio("remote"),
        study: radio("study")
      };
    }

    function crcRun() {
      const container = document.getElementById("crc-results");
      if (!careerRealityData) {
        if (container) {
          container.hidden = false;
          container.innerHTML = '<div class="crc-panel"><p class="crc-panel-label">Data not generated yet</p><p class="crc-method-body">Run <code>python3 scripts/train_career_signal_model.py</code> then <code>python3 scripts/process_career_reality.py</code> to enable Career Reality Check.</p></div>';
        }
        return;
      }
      const inputs = crcReadInputs();
      const anchor = crcFindAnchor(inputs.targetRaw);
      const path = crcGetPath(inputs.experience);
      const verdictKey = crcDecideVerdict(anchor, inputs);
      const buckets = crcBuildBuckets(path, anchor, inputs, verdictKey);
      const skills = crcBuildSkills(path, anchor, inputs);
      const keywords = crcBuildKeywords(path, anchor, buckets);
      const verdictText = crcComposeVerdictText(verdictKey, anchor, inputs, buckets, skills);
      const caution = crcBuildCaution(anchor, inputs);
      const plan = crcBuildPlan(buckets, skills, inputs, anchor);

      // Evidence is anchored on the target; with no target it falls back to the
      // strongest occupation in the user's experience field so the panel still
      // shows the data behind the verdict.
      const evidenceOcc = anchor?.occ || crcTopOccupationInField(CRC_EXPERIENCE_FIELDS[inputs.experience]);
      const matchedSkills = crcMatchedSkills(anchor, inputs);
      const evidence = crcBuildEvidence(evidenceOcc, inputs, matchedSkills);

      crcRenderResult({
        verdictKey, verdictText, evidence, buckets, skills, keywords, plan, caution,
        anchorTerm: evidenceOcc ? evidenceOcc.term : null
      });
      document.getElementById("crc-results").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function crcInitSection(data) {
      careerRealityData = data || null;

      const regionSelect = document.getElementById("crc-region");
      if (regionSelect) {
        const regions = Array.isArray(data?.regions) ? data.regions : [];
        const options = ['<option value="">Anywhere in Sweden</option>']
          .concat(regions.map((r) => `<option value="${escapeHtml(r.term)}">${escapeHtml(r.term)}</option>`));
        regionSelect.innerHTML = options.join("");
      }

      // Pill groups: keep the radio + the .is-active styling in sync.
      document.querySelectorAll(".crc-pills").forEach((group) => {
        group.addEventListener("change", () => {
          group.querySelectorAll(".crc-pill").forEach((pill) => {
            const input = pill.querySelector("input");
            pill.classList.toggle("is-active", !!input && input.checked);
          });
        });
      });

      const modelTag = document.getElementById("crc-model-tag");
      if (modelTag) {
        const src = data?.forecast_model_source;
        if (src === "ml") modelTag.innerHTML = "Trend uses an <strong>ML demand forecast</strong> &middot; 4-week horizon";
        else if (src === "baseline") modelTag.innerHTML = "Trend uses a <strong>moving-average baseline</strong> (ML runtime not active)";
        else modelTag.innerHTML = "Trend uses <strong>transparent rules</strong>";
        modelTag.hidden = false;
      }

      const form = document.getElementById("crc-form");
      if (form) {
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          try {
            crcRun();
          } catch (error) {
            console.error("Career Reality Check failed", error);
          }
        });
      }
    }

    async function init() {
      const data = await fetchLocalJson("data/career_reality.json");
      crcInitSection(data);
      const overlay = document.getElementById("loading-overlay");
      if (overlay) overlay.classList.add("hidden");
    }

    window.addEventListener("DOMContentLoaded", () => {
      init().catch((error) => {
        console.error("Career Reality Check init failed", error);
        const overlay = document.getElementById("loading-overlay");
        if (overlay) overlay.classList.add("hidden");
      });
    });
