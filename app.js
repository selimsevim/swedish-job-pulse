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

    // Target-field guardrail. The target job decides which career-path template
    // drives the role/skill recommendations — NOT the user's current experience.
    // This stops a "data analyst" target from being answered with education
    // roles. Maps a target phrase to a career_paths experience_key. First hit
    // wins, so analytics ("data analyst") resolves to the reporting/admin
    // bridge, while "developer" resolves to the IT track.
    const CRC_TARGET_PATHS = [
      { path: "admin", kw: ["data analyst", "dataanalyt", "analyst", "analytiker", "business intelligence", "bi assistant", "bi developer", "reporting", "rapporter", "controller", "utredare", "operations coordinator", "verksamhetsutvecklare"] },
      { path: "it", kw: ["developer", "utveckl", "software", "mjukvar", "programmer", "devops", "frontend", "backend", "fullstack", "systemutveckl", "data engineer", "dataingenjör", "data scientist", "cyber", "it-säkerhet", "fullstack"] },
      { path: "education", kw: ["teacher", "lärare", "förskoll", "pedagog", "barnskötare", "elevassistent", "fritidsled", "teaching", "preschool", "school teacher"] },
      { path: "healthcare", kw: ["nurse", "sjukskötersk", "undersköter", "läkare", "doctor", "vårdbiträd", "healthcare", "barnmorsk", "tandläk"] },
      { path: "logistics", kw: ["truck", "lastbil", "warehouse", "lager", "logistic", "logistik", "chaufför", "terminal", "forklift", "driver"] },
      { path: "sales", kw: ["sales", "säljare", "marketing", "marknadsför", "account manager", "key account", "retail", "butikssälj"] },
      { path: "restaurant", kw: ["chef", "kock", "waiter", "servit", "restaurant", "restaurang", "barista", "kitchen", "kök", "bartender"] },
      { path: "customer_service", kw: ["customer service", "customer support", "kundtjänst", "kundsupport", "support specialist"] },
      { path: "admin", kw: ["admin", "coordinator", "koordinator", "ekonom", "accountant", "receptionist", "handläggare", "planerare"] }
    ];

    // Human-readable label for the user's current experience area.
    const CRC_EXPERIENCE_LABEL = {
      customer_service: "customer service", sales: "sales", admin: "admin",
      it: "IT/tech", healthcare: "healthcare", education: "education",
      restaurant: "restaurant/service", logistics: "logistics", none: "no fixed field"
    };

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

    // Which career-path template should drive the recommendations, based on the
    // TARGET job. Returns a career_paths experience_key, or null when unknown.
    function crcTargetPathKey(targetText) {
      const t = crcNorm(targetText);
      if (!t) return null;
      for (const entry of CRC_TARGET_PATHS) {
        if (entry.kw.some((kw) => t.includes(kw))) return entry.path;
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

    function crcBuildBuckets(path, anchor, inputs, verdictKey, pathKey) {
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

      // Backfill "realistic now" from the strongest occupations in the path's
      // own field (the target field when a target was given) if the curated
      // list came up short — never from an unrelated field.
      if (nowRoles.length < 3) {
        const fieldId = CRC_EXPERIENCE_FIELDS[pathKey] || CRC_EXPERIENCE_FIELDS[inputs.experience];
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
      // Skills the target field's growing-signal skills, for the "growing" tag.
      const growingSet = new Set((anchor?.occ?.related_skills || [])
        .filter((s) => s.signal === "growing").map((s) => crcNorm(s.skill)));
      const push = (skill) => {
        const key = crcNorm(skill);
        if (!key || seen.has(key) || have.has(key)) return;
        seen.add(key);
        out.push({ skill, growing: growingSet.has(key) });
      };
      // Lead with the curated skills for the TARGET path (these are the
      // field-correct ones: e.g. SQL / Excel / Power BI for an analytics
      // target), then add any market-growing skills for the target field.
      (path?.skills_to_add || []).forEach(push);
      (anchor?.occ?.related_skills || []).forEach((s) => {
        if (s.signal === "growing") push(s.skill);
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

    // Join a short list into readable prose: "a", "a and b", "a, b, and c".
    function crcJoinList(items) {
      const list = (items || []).filter(Boolean);
      if (!list.length) return "";
      if (list.length === 1) return list[0];
      if (list.length === 2) return `${list[0]} and ${list[1]}`;
      return `${list.slice(0, -1).join(", ")}, and ${list[list.length - 1]}`;
    }

    // 1) Main answer — one plain-language sentence the user reads first.
    function crcComposeMainAnswer(key, anchor, inputs) {
      const occ = anchor?.occ;
      const target = inputs.targetRaw.trim() || (occ ? occ.term : null);
      if (key === "now") {
        return target
          ? `Apply now — ${target} is a realistic target for you.`
          : "Apply now — you have realistic options from your experience.";
      }
      if (key === "soon") {
        return target
          ? `Don't make ${target} your main application lane yet.`
          : "This direction is reachable — but not your first lane yet.";
      }
      if (key === "risky") {
        return target
          ? `${crcCapitalize(target)} is a long shot right now — don't lead with it.`
          : "This path is a long shot right now — don't lead with it.";
      }
      return "Add a target job for a sharper read. Meanwhile, here's a safe place to start.";
    }

    // 2) Why — 3–4 plain reasons. Never shows "unknown" as a reason.
    function crcBuildReasons(key, occ, anchor, inputs, buckets, skills, matchedSkills, bridgeNote) {
      const reasons = [];
      const fieldLabel = occ?.field_label || "this field";
      const targetWord = (inputs.targetRaw.trim() || occ?.term || "these").toLowerCase();
      const nowNames = buckets.now.slice(0, 3).map((r) => r.name);
      const toAdd = skills.slice(0, 2).map((s) => s.skill);
      const regionSig = occ ? crcRegionSignal(occ.field_id, inputs.region) : null;
      const heavy = occ && CRC_LANGUAGE_HEAVY.has(occ.field_id);
      const englishOk = occ && (CRC_ENGLISH_OK.has(occ.field_id) || occ.remote_signal === "strong");
      const isIt = occ?.field_id === "apaJ_2ja_LuF";

      if (key === "now") {
        if (regionSig === "strong" && inputs.region) reasons.push(`${fieldLabel} demand is strong in ${inputs.region}.`);
        if (occ?.demand_level === "high") reasons.push("Demand is healthy right now.");
        else if (occ?.demand_level === "medium") reasons.push("Demand is steady right now.");
        if (matchedSkills.length) reasons.push(`Your ${crcJoinList(matchedSkills.map((m) => m.skill))} match what these roles ask for.`);
        if (occ?.demand_trend === "rising") reasons.push("The 4-week demand forecast is trending up.");
        if (occ?.crowding_risk === "high") reasons.push("It's competitive — apply broadly, not to one title.");
        if (!reasons.length) reasons.push("Your profile is a reasonable fit for current openings.");
      } else {
        if (regionSig === "weak" && inputs.region) reasons.push(`Local ${fieldLabel} demand is weaker in ${inputs.region}.`);
        if (occ?.crowding_risk === "high") reasons.push(`${crcCapitalize(targetWord)} roles are competitive right now.`);
        if (inputs.level === "entry" && occ?.entry_level_signal === "weak") reasons.push("Most ads here still expect some experience.");
        if (inputs.swedish === "english" && heavy && !englishOk) reasons.push(`Most ${fieldLabel} roles expect working Swedish.`);
        if (toAdd.length) {
          const proof = isIt ? [...toAdd, "a portfolio project"] : toAdd;
          if (matchedSkills.length) reasons.push(`${crcCapitalize(matchedSkills[0].skill)} helps, but your profile still needs ${crcJoinList(proof)}.`);
          else reasons.push(`Your profile still needs ${crcJoinList(proof)}.`);
        }
        if (occ?.demand_trend === "declining") reasons.push("Demand is cooling over the next few weeks.");
        if (nowNames.length) reasons.push(`Stronger entry routes exist: ${crcJoinList(nowNames)}.`);
      }
      const ordered = reasons.filter(Boolean);
      if (bridgeNote) ordered.unshift(bridgeNote);  // lead with the bridge framing
      return ordered.slice(0, 4);
    }

    // 4) Keep as stretch target — the target plus nearby reachable roles.
    // Reachable roles only: the "risky / senior" list would add far-fetched
    // titles (e.g. Specialistläkare for an admin seeker) and read as noise.
    function crcBuildStretch(anchor, inputs, buckets) {
      const out = [];
      const seen = new Set();
      const push = (name) => {
        const k = crcNorm(name);
        if (k && !seen.has(k)) { seen.add(k); out.push(name); }
      };
      // The user's own target is the headline stretch item.
      if (anchor && !anchor.viaAlias) push(anchor.occ.term);
      else if (inputs.targetRaw.trim()) push(crcCapitalize(inputs.targetRaw.trim()));
      buckets.reach.forEach((r) => push(r.name));
      return out.slice(0, 4);
    }

    // 5) Do this next — max 4 concrete bullets.
    function crcBuildNextSteps(key, anchor, inputs, buckets, skills, keywords) {
      const steps = [];
      const nowNames = buckets.now.slice(0, 3).map((r) => r.name);
      const toAdd = skills.slice(0, 2).map((s) => s.skill);
      const kw = keywords.slice(0, 5);
      const target = inputs.targetRaw.trim() || anchor?.occ?.term || null;
      const isIt = anchor?.occ?.field_id === "apaJ_2ja_LuF";

      if (key === "now") {
        steps.push(`Apply to 6–8 of the roles above this week${nowNames.length ? ` (start with ${crcJoinList(nowNames.slice(0, 2))})` : ""}.`);
        if (toAdd.length) steps.push(`Sharpen ${crcJoinList(toAdd)} to stand out.`);
        if (kw.length) steps.push(`Search for ${kw.map((k) => `"${k}"`).join(", ")}.`);
        steps.push("Tailor each CV to the specific ad — don't send the same one everywhere.");
      } else {
        steps.push(`Apply to 6–8 realistic roles this week${nowNames.length ? ` — ${crcJoinList(nowNames)}` : ""}.`);
        if (toAdd.length) {
          steps.push(isIt
            ? `Add ${crcJoinList(toAdd)}, and build one small portfolio project to prove it.`
            : `Add ${crcJoinList(toAdd)} to your CV.`);
        }
        if (kw.length) steps.push(`Search for ${kw.map((k) => `"${k}"`).join(", ")}.`);
        if (target) {
          steps.push(isIt
            ? `Apply to ${target.toLowerCase()} roles only when the ad accepts junior applicants or portfolio proof.`
            : `Apply to ${target.toLowerCase()} roles only when the ad welcomes junior or entry-level applicants.`);
        } else {
          steps.push("Add a target job above for a sharper, role-specific read.");
        }
      }
      return steps.slice(0, 4);
    }

    // 6) Data signal — one compact muted line. Skips "unknown" tokens entirely.
    // Demand is shown as a forecast direction word ("Rising/Stable/Cooling
    // demand") rather than a raw percentage, which keeps the ML influence
    // visible without surfacing noisy or alarming numbers.
    function crcBuildSignalLine(occ, inputs) {
      if (!occ) return null;
      const parts = [];
      const trendWord = { rising: "Rising", stable: "Stable", declining: "Cooling" }[occ.demand_trend];
      if (trendWord) parts.push(`${trendWord} demand`);
      else if (occ.demand_level && occ.demand_level !== "unknown") parts.push(`${occ.demand_level} demand`);
      if (occ.crowding_risk && occ.crowding_risk !== "unknown") parts.push(`${occ.crowding_risk} crowding`);
      const rs = crcRegionSignal(occ.field_id, inputs.region);
      if (rs) parts.push(`${rs} regional fit`);
      if (occ.remote_signal && occ.remote_signal !== "unknown") parts.push(`${occ.remote_signal} remote signal`);
      return parts.length ? parts.join(" · ") : null;
    }

    function crcRenderResult(model) {
      const container = document.getElementById("crc-results");
      if (!container) return;

      const verdictMod = { now: "now", soon: "soon", risky: "risky", unknown: "unknown" }[model.verdictKey] || "unknown";

      const roleList = (items, label, stretch) => items.length ? `
        <div class="crc-panel">
          <p class="crc-panel-label">${escapeHtml(label)}</p>
          <ul class="crc-rolelist${stretch ? " crc-rolelist--stretch" : ""}">
            ${items.map((n) => `<li class="crc-role-simple">${escapeHtml(n)}</li>`).join("")}
          </ul>
        </div>` : "";

      const whyHtml = model.reasons.length ? `
        <div class="crc-panel">
          <p class="crc-panel-label">Why</p>
          <ul class="crc-reasons">
            ${model.reasons.map((r) => `<li class="crc-reason">${escapeHtml(r)}</li>`).join("")}
          </ul>
        </div>` : "";

      const nextHtml = model.nextSteps.length ? `
        <div class="crc-panel crc-plan">
          <p class="crc-panel-label">Do this next</p>
          <ul class="crc-plan-list">
            ${model.nextSteps.map((s, i) => `<li class="crc-plan-item"><span class="crc-plan-num">${i + 1}</span><span>${escapeHtml(s)}</span></li>`).join("")}
          </ul>
        </div>` : "";

      const signalHtml = model.signalLine
        ? `<p class="crc-signal-line"><b>Data signal</b> ${escapeHtml(model.signalLine)}</p>`
        : "";

      container.innerHTML = `
        <div class="crc-verdict crc-verdict--${verdictMod}">
          <div class="crc-verdict-body">
            <span class="crc-verdict-kicker">Main answer</span>
            <h3 class="crc-verdict-title">${escapeHtml(model.mainAnswer)}</h3>
          </div>
        </div>
        ${whyHtml}
        ${roleList(model.applyFirst, "Apply for these first", false)}
        ${roleList(model.stretch, "Keep as stretch target", true)}
        ${nextHtml}
        ${signalHtml}`;

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

      // Target-field guardrail: the TARGET job decides which career path drives
      // the role / skill / keyword recommendations, so they never drift into an
      // unrelated field (e.g. education roles under a "data analyst" verdict).
      // Falls back to the experience path only when the target is unknown.
      const targetPathKey = crcTargetPathKey(inputs.targetRaw);
      const pathKey = targetPathKey || inputs.experience;
      const path = crcGetPath(pathKey);

      const verdictKey = crcDecideVerdict(anchor, inputs);
      const buckets = crcBuildBuckets(path, anchor, inputs, verdictKey, pathKey);
      const skills = crcBuildSkills(path, anchor, inputs);
      const keywords = crcBuildKeywords(path, anchor, buckets);
      const matchedSkills = crcMatchedSkills(anchor, inputs);

      // The reference occupation for the verdict / signal stays on the TARGET;
      // with no target it falls back to the experience field.
      const occ = anchor?.occ || crcTopOccupationInField(CRC_EXPERIENCE_FIELDS[inputs.experience]);

      // Bridge framing when the user's experience and target are different
      // fields, so the cross-field recommendation is explained, not silent.
      const bridge = (targetPathKey && inputs.experience !== "none" && targetPathKey !== inputs.experience)
        ? `Your background is in ${CRC_EXPERIENCE_LABEL[inputs.experience] || inputs.experience}, but you're targeting ${inputs.targetRaw.trim() || (anchor && anchor.occ.term) || "a different field"} — the roles below are the bridge.`
        : null;

      crcRenderResult({
        verdictKey,
        mainAnswer: crcComposeMainAnswer(verdictKey, anchor, inputs),
        reasons: crcBuildReasons(verdictKey, occ, anchor, inputs, buckets, skills, matchedSkills, bridge),
        applyFirst: buckets.now.slice(0, 5).map((r) => r.name),
        stretch: verdictKey === "now" ? [] : crcBuildStretch(anchor, inputs, buckets),
        nextSteps: crcBuildNextSteps(verdictKey, anchor, inputs, buckets, skills, keywords),
        signalLine: crcBuildSignalLine(occ, inputs)
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

    // =====================================================================
    // CV Job Fit Scanner
    // The PDF is parsed in the browser (pdf.js) and never leaves the device.
    // Extraction + matching mirror scripts/build_cv_match_index.py so the
    // offline synthetic-CV evaluation tests the same pipeline. Live demand /
    // crowding / trend signals are reused from career_reality.json.
    // =====================================================================
    let cvIndex = null;
    let cvSamples = [];

    // Display names for canonical (lower_snake) skill / token ids.
    const CV_PRETTY = {
      sfmc: "SFMC", ampscript: "AMPscript", ssjs: "SSJS", crm: "CRM", sql: "SQL",
      apis: "APIs", api: "API", etl: "ETL", kpi: "KPI", seo: "SEO", bi: "BI",
      power_bi: "Power BI", html_css: "HTML/CSS", cicd: "CI/CD", devops: "DevOps",
      data_cloud: "Salesforce Data Cloud", machine_learning: "Machine learning",
      marketing_automation: "Marketing automation", customer_service: "Customer service",
      office_tools: "Office tools", account_management: "Account management",
      data_visualization: "Data visualization", supply_chain: "Supply chain",
      driving_license: "Driving licence", elderly_care: "Elderly care",
      patient_care: "Patient care", incident_response: "Incident response",
      test_automation: "Test automation", project_management: "Project management",
      financial_analysis: "Financial analysis", social_media: "Social media",
      google_analytics: "Google Analytics", email_marketing: "Email marketing"
    };
    const CV_WORD_ACRONYM = { sql: "SQL", crm: "CRM", api: "API", apis: "APIs", etl: "ETL", kpi: "KPI", seo: "SEO", bi: "BI", sfmc: "SFMC" };
    function crcCvPretty(skill) {
      const s = String(skill || "").toLowerCase();
      if (CV_PRETTY[s]) return CV_PRETTY[s];
      return s.replace(/_/g, " ").split(" ")
        .map((w) => CV_WORD_ACRONYM[w] || (w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
    }

    // Friendly role-family wording for the headline (field_label is too formal).
    const CV_FIELD_PHRASE = {
      RPTn_bxG_ExZ: "CRM / marketing", X82t_awd_Qyc: "analytics / reporting",
      apaJ_2ja_LuF: "data / developer", NYW6_mP6_vwf: "healthcare",
      ASGV_zcE_bWf: "logistics", MVqp_eS8_kDZ: "education",
      ScKy_FHB_7wT: "hospitality", GazW_2TU_kJw: "social care"
    };
    function crcCvFieldPhrase(role) {
      return (role && CV_FIELD_PHRASE[role.field_id]) || role?.field_label || "these";
    }

    // Hard / technical skills are the gaps worth surfacing first.
    const CV_HARD_GAPS = new Set([
      "sql", "power bi", "statistics", "python", "dashboards", "etl",
      "machine learning", "data visualization", "salesforce marketing cloud",
      "marketing automation", "segmentation", "google analytics", "seo",
      "cloud", "docker", "kubernetes", "ci/cd", "test automation", "apis",
      "javascript", "financial analysis", "accounting", "crm", "excel"
    ]);

    // Extract a structured profile from raw CV text (mirror of the Python).
    // ---- Layer 2: retrieval (TF-IDF cosine; mirrors build_cv_match_index.py).
    // Synonym/domain expansion collapses surface forms (SFMC == Salesforce
    // Marketing Cloud == Martech) so technical CRM/martech CVs don't get
    // flattened into "digital marketing". A Nebius job swaps this vector space
    // for BGE-M3 / Qwen3 embeddings behind the same cosine contract.
    let cvStopSet = null;
    const CV_TOKEN_RE = /[a-z0-9_+#]+/g;
    const CV_SEN_ORDER = { entry: 0, mid: 1, senior: 2 };

    function crcCvCanon(text) {
      let low = " " + String(text || "").toLowerCase() + " ";
      (cvIndex?.synonyms || []).forEach(([phrase, repl]) => { low = low.split(phrase).join(repl); });
      return low;
    }
    function crcCvTokenize(text) {
      if (!cvStopSet) cvStopSet = new Set(cvIndex?.stopwords || []);
      return (crcCvCanon(text).match(CV_TOKEN_RE) || [])
        .filter((t) => t.length >= 2 && !cvStopSet.has(t));
    }
    function crcCvTf(tokens) {
      const c = {};
      tokens.forEach((t) => { c[t] = (c[t] || 0) + 1; });
      const o = {};
      for (const t in c) o[t] = 1 + Math.log(c[t]);
      return o;
    }
    function crcCvEmbedQuery(text) {
      const idf = cvIndex?.idf || {};
      const tf = crcCvTf(crcCvTokenize(text));
      const vec = {};
      let norm = 0;
      for (const t in tf) {
        if (idf[t] !== undefined) { const v = tf[t] * idf[t]; vec[t] = v; norm += v * v; }
      }
      norm = Math.sqrt(norm) || 1;
      for (const t in vec) vec[t] /= norm;
      return vec;
    }
    function crcCvCosine(q, r) {
      let a = q, b = r;
      if (Object.keys(q).length > Object.keys(r).length) { a = r; b = q; }
      let s = 0;
      for (const t in a) if (b[t] !== undefined) s += a[t] * b[t];
      return s;
    }

    // ---- Layer 1: CV understanding (structured profile).
    function crcCvExtract(text) {
      const low = crcCvCanon(text);
      const skills = (cvIndex?.skill_vocab || [])
        .filter((s) => s.variants.some((v) => low.includes(v)))
        .map((s) => s.skill);
      const roles = (cvIndex?.roles || [])
        .filter((r) => (r.aliases || []).some((a) => low.includes(a)))
        .map((r) => r.title);

      let swedish = "none";
      if (/svenska|swedish/.test(low)) {
        const nearAfter = (words) => new RegExp(`(svenska|swedish)\\s*[:/,-]?\\s*[^.;,\\n]{0,30}${words}`).test(low);
        const nearBefore = (words) => new RegExp(`${words}\\s*[^.;,\\n]{0,15}(svenska|swedish)`).test(low);
        const native = "(modersmål|native|flytande|fluent)";
        const good = "(good|goda|arbetsnivå|working|professional|b2|c1)";
        const basic = "(basic|grundläggande|sfi|a1|a2|b1)";
        if (nearAfter(native) || nearBefore(native)) swedish = "native";
        else if (nearAfter(good) || nearBefore(good)) swedish = "good";
        else if (nearAfter(basic) || nearBefore(basic)) swedish = "basic";
        else swedish = "basic";
      }
      const languages = [];
      if (low.includes("english") || low.includes("engelska")) languages.push("English");
      if (swedish !== "none") languages.push("Swedish (" + swedish + ")");

      const years = [...low.matchAll(/(\d{1,2})\+?\s*(?:years|år)/g)].map((m) => Number(m[1]));
      const maxY = years.length ? Math.max(...years) : 0;
      let seniority;
      if (/\b(senior|lead|head|principal|architect|chef)\b/.test(low)) seniority = "senior";
      else if (/\b(junior|intern|trainee|student|entry)\b/.test(low)) seniority = "entry";
      else if (maxY >= 6) seniority = "senior";
      else if (maxY >= 2) seniority = "mid";
      else seniority = "entry";

      return {
        text: String(text || ""), skills, roles, languages, swedish, seniority,
        years: maxY, weakSwedish: swedish === "none" || swedish === "basic"
      };
    }

    // ---- Layer 3: rerank (semantic + skill + seniority + language).
    function crcCvRank(profile) {
      const qvec = crcCvEmbedQuery(profile.text);
      const cv = new Set(profile.skills);
      return (cvIndex?.roles || []).map((r) => {
        const sem = crcCvCosine(qvec, r.vector || {});
        const req = r.required_skills || [];
        const cov = req.length ? req.filter((s) => cv.has(s)).length / req.length : 0;
        const gap = CV_SEN_ORDER[r.seniority] - (CV_SEN_ORDER[profile.seniority] ?? 0);
        const senPen = gap > 0 ? 0.12 * gap : 0;
        const langPen = (r.language_sensitive && profile.weakSwedish) ? 0.12 : 0;
        const fit = Math.max(0, 0.55 * sem + 0.30 * cov - senPen - langPen);
        return {
          title: r.title, domain: r.domain, field_id: r.field_id, field_label: r.field_label,
          seniority: r.seniority, semantic: sem, coverage: cov, gap, fit,
          missing: req.filter((s) => !cv.has(s)),
          languageSensitive: !!r.language_sensitive, keywords: r.search_keywords || []
        };
      }).sort((a, b) => b.fit - a.fit);
    }

    function crcCvBucket(profile, scored) {
      const weights = {};
      scored.slice(0, 6).forEach((s) => { weights[s.domain] = (weights[s.domain] || 0) + s.fit; });
      let pdomain = null, bw = 0;
      for (const d in weights) if (weights[d] > bw) { bw = weights[d]; pdomain = d; }
      const adjMap = cvIndex?.domain_adjacency || {};
      const adjacent = new Set(adjMap[pdomain] || []);
      if (pdomain) adjacent.add(pdomain);
      // "Confusable" domains: ones that treat your domain as adjacent, but you
      // don't treat as yours (e.g. digital marketing vs a technical martech CV).
      // These belong in "not your main lane" even at low fit, to make the point.
      const confusable = new Set();
      if (pdomain) {
        for (const d in adjMap) {
          if (d !== pdomain && (adjMap[d] || []).includes(pdomain) && !adjacent.has(d)) confusable.add(d);
        }
      }
      const best = [], adj = [], avoid = [];
      scored.forEach((s) => {
        const overreach = s.gap >= 2 || (s.seniority === "senior" && s.gap > 0);
        const onLane = s.domain === pdomain;
        const nearLane = adjacent.has(s.domain);
        const strong = s.fit >= 0.30 && (s.semantic >= 0.12 || s.coverage >= 0.5);
        if (overreach) {
          if (s.fit >= 0.12) avoid.push(s);            // aspirational over-reach with real signal
        } else if (onLane && strong) {
          best.push(s);
        } else if ((onLane || nearLane) && (s.fit >= 0.20 || s.semantic >= 0.15)) {
          adj.push(s);
        } else if (confusable.has(s.domain)) {
          avoid.push(s);                                // looks adjacent but isn't your lane
        } else if (s.fit >= 0.22) {
          avoid.push(s);                                // off-lane but a notable, mismatched pull
        }
        // else: irrelevant / near-zero fit -> not shown at all
      });
      return { pdomain, best: best.slice(0, 6), adj: adj.slice(0, 5), avoid: avoid.slice(0, 5) };
    }

    function crcCvDomainLabel(domain) {
      return (cvIndex?.domain_label || {})[domain] || domain || "these";
    }

    function crcCvBuildReport(profile) {
      const scored = crcCvRank(profile);
      const { pdomain, best, adj, avoid } = crcCvBucket(profile, scored);

      let tone, mainAnswer;
      if (best.length) {
        tone = "now";
        mainAnswer = `Your CV is strongest for ${crcCvDomainLabel(pdomain)} roles.`;
      } else if (adj.length) {
        tone = "soon";
        mainAnswer = `Your CV is close to ${crcCvDomainLabel(adj[0].domain)} roles — strengthen the proof first.`;
      } else {
        tone = "risky";
        mainAnswer = "Your CV doesn't match a clear role family yet — here's what to strengthen.";
      }

      // Missing skills: gaps from best + adjacent roles, hard/technical first.
      const freq = new Map();
      [...best, ...adj].forEach((r) => r.missing.forEach((s) => freq.set(s, (freq.get(s) || 0) + 1)));
      let missing = [...freq.entries()]
        .sort((a, b) => ((CV_HARD_GAPS.has(b[0]) ? 1 : 0) - (CV_HARD_GAPS.has(a[0]) ? 1 : 0)) || (b[1] - a[1]))
        .map((e) => e[0]).slice(0, 6);
      if (profile.weakSwedish && [...best, ...adj].some((r) => r.languageSensitive)) {
        missing = missing.slice(0, 5);
        missing.push("swedish working proficiency");
      }

      // CV weaknesses (heuristics on the raw text + profile).
      const t = profile.text || "";
      const resultWords = /(increase|increased|reduc|grew|growth|%|procent|\bkpi\b|results?|resultat|saved|boosted|improv|ökade|minskade)/i.test(t);
      const weaknesses = [];
      if (!resultWords) weaknesses.push("Add measurable impact — numbers, %, and what changed because of your work.");
      if (profile.skills.length < 5) weaknesses.push("Add a clear technical skills section that lists your tools.");
      if (!profile.languages.length) weaknesses.push("State your Swedish and English level explicitly.");
      if (profile.seniority === "senior" && pdomain === "crm_martech") {
        weaknesses.push("Frame senior scope explicitly — architecture ownership and 'solution architect' positioning.");
      }
      if (!weaknesses.length) weaknesses.push("Strong structure — focus on closing the missing skills above.");

      // Keywords from best + adjacent roles.
      const seen = new Set();
      const keywords = [];
      [...best, ...adj].forEach((r) => (r.keywords || []).forEach((k) => {
        const key = k.toLowerCase();
        if (!seen.has(key)) { seen.add(key); keywords.push(k); }
      }));

      // 7-day action plan (max 4).
      const plan = [];
      const bestTitles = best.slice(0, 2).map((r) => r.title);
      plan.push(`Apply to ${Math.max(6, best.length * 2)} best-fit roles this week${bestTitles.length ? ` — e.g. ${bestTitles.join(", ")}` : ""}.`);
      if (missing.length) {
        const gaps = missing.slice(0, 2).map(crcCvPretty);
        plan.push(`Build proof for ${gaps.join(" and ")} — a focused project or short course.`);
      }
      plan.push("Rewrite your CV: add measurable impact and a clear skills section.");
      if (keywords.length) plan.push(`Search Platsbanken for ${keywords.slice(0, 4).map((k) => `"${k}"`).join(", ")}.`);

      const sigOcc = best[0] ? crcTopOccupationInField(best[0].field_id)
        : (adj[0] ? crcTopOccupationInField(adj[0].field_id) : null);
      const signalLine = sigOcc ? crcBuildSignalLine(sigOcc, { region: "" }) : null;

      return {
        tone, mainAnswer, primaryDomain: pdomain, domainLabel: crcCvDomainLabel(pdomain),
        best: best.map((r) => r.title), adjacent: adj.map((r) => r.title), avoid: avoid.map((r) => r.title),
        missing, weaknesses, keywords: keywords.slice(0, 7), plan, signalLine,
        tools: profile.skills.slice(0, 7).map(crcCvPretty)
      };
    }

    function crcCvRenderReport(report, profile) {
      const container = document.getElementById("cv-results");
      if (!container) return;

      const rolePanel = (label, items, modifier) => items.length ? `
        <div class="crc-panel">
          <p class="crc-panel-label">${escapeHtml(label)}</p>
          <ul class="crc-rolelist${modifier ? ` crc-rolelist--${modifier}` : ""}">
            ${items.map((n) => `<li class="crc-role-simple">${escapeHtml(n)}</li>`).join("")}
          </ul>
        </div>` : "";

      const tagPanel = (label, items, gap) => items.length ? `
        <div class="crc-panel">
          <p class="crc-panel-label">${escapeHtml(label)}</p>
          <div class="cv-tags">
            ${items.map((s) => `<span class="cv-tag${gap ? " cv-tag--gap" : ""}">${escapeHtml(gap ? crcCvPretty(s) : s)}</span>`).join("")}
          </div>
        </div>` : "";

      const weaknessHtml = report.weaknesses.length ? `
        <div class="crc-panel">
          <p class="crc-panel-label">Improve your CV by adding</p>
          <ul class="crc-reasons">
            ${report.weaknesses.map((w) => `<li class="crc-reason">${escapeHtml(w)}</li>`).join("")}
          </ul>
        </div>` : "";

      const planHtml = report.plan.length ? `
        <div class="crc-panel crc-plan">
          <p class="crc-panel-label">7-day action plan</p>
          <ul class="crc-plan-list">
            ${report.plan.map((s, i) => `<li class="crc-plan-item"><span class="crc-plan-num">${i + 1}</span><span>${escapeHtml(s)}</span></li>`).join("")}
          </ul>
        </div>` : "";

      const signalHtml = report.signalLine
        ? `<p class="crc-signal-line"><b>Market signal</b> ${escapeHtml(report.signalLine)}</p>` : "";

      const tools = (report.tools && report.tools.length) ? report.tools.join(", ") : "no clear tools detected";
      const summary = `<p class="cv-summary"><b>Read from your CV</b> ${escapeHtml(profile.seniority)} level · ${escapeHtml(report.domainLabel)} · ${escapeHtml(tools)} · ${escapeHtml(profile.languages.join(", ") || "no language level stated")}</p>`;

      container.innerHTML = `
        ${summary}
        <div class="crc-verdict crc-verdict--${report.tone}">
          <div class="crc-verdict-body">
            <span class="crc-verdict-kicker">Job fit report</span>
            <h3 class="crc-verdict-title">${escapeHtml(report.mainAnswer)}</h3>
          </div>
        </div>
        ${rolePanel("Best-fit roles now", report.best, "")}
        ${rolePanel("Adjacent roles", report.adjacent, "stretch")}
        ${rolePanel("Not your main lane", report.avoid, "avoid")}
        ${tagPanel("Your CV is missing", report.missing, true)}
        ${weaknessHtml}
        ${tagPanel("Search keywords", report.keywords, false)}
        ${planHtml}
        ${signalHtml}`;
      container.hidden = false;
    }

    function crcCvSetStatus(message, isError) {
      const el = document.getElementById("cv-status");
      if (!el) return;
      if (!message) { el.hidden = true; return; }
      el.textContent = message;
      el.classList.toggle("cv-status--error", !!isError);
      el.hidden = false;
    }

    function crcCvClearReport() {
      const container = document.getElementById("cv-results");
      if (!container) return;
      container.hidden = true;
      container.innerHTML = "";
    }

    function crcCvAnalyseText(text, sourceLabel) {
      if (!cvIndex) { crcCvSetStatus("CV index not loaded — run scripts/build_cv_match_index.py.", true); return; }
      crcCvClearReport();
      const cleanText = String(text || "").trim();
      if (cleanText.length < 40) {
        crcCvSetStatus("Not enough CV information yet. Add role titles, skills, tools, language level, and recent work or study history.", true);
        return;
      }
      const profile = crcCvExtract(cleanText);
      if (!profile.skills.length && !profile.roles.length) {
        crcCvSetStatus("Not enough recognisable CV information yet. Add role titles, skills, tools, language level, and recent work or study history.", true);
        return;
      }
      const report = crcCvBuildReport(profile);
      crcCvRenderReport(report, profile);
      crcCvSetStatus(sourceLabel ? `Analysed ${sourceLabel}. Nothing was uploaded or stored.` : null, false);
      document.getElementById("cv-results").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    async function crcCvReadPdf(file) {
      if (!window.pdfjsLib) throw new Error("pdf.js not available");
      window.pdfjsLib.GlobalWorkerOptions.workerSrc =
        "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
      const buffer = await file.arrayBuffer();
      const pdf = await window.pdfjsLib.getDocument({ data: buffer }).promise;
      let text = "";
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const content = await page.getTextContent();
        text += content.items.map((it) => it.str).join(" ") + "\n";
      }
      return text;
    }

    async function crcCvHandleFile(file) {
      if (!file) return;
      if (!/pdf$/i.test(file.name) && file.type !== "application/pdf") {
        crcCvClearReport();
        crcCvSetStatus("Please choose a PDF file.", true);
        return;
      }
      crcCvSetStatus("Reading your CV in your browser…", false);
      try {
        const text = await crcCvReadPdf(file);
        crcCvAnalyseText(text, file.name);
      } catch (error) {
        console.error("CV read failed", error);
        crcCvSetStatus("Could not read that PDF in the browser. Try another PDF, or use a sample below.", true);
      }
    }

    function crcCvInit(index, samples) {
      cvIndex = index || null;
      cvSamples = Array.isArray(samples?.cvs) ? samples.cvs : [];

      const fileInput = document.getElementById("cv-file");
      const browse = document.getElementById("cv-browse");
      const drop = document.getElementById("cv-drop");
      const textArea = document.getElementById("cv-text");
      const analyseText = document.getElementById("cv-analyse-text");
      if (browse && fileInput) browse.addEventListener("click", () => fileInput.click());
      if (fileInput) fileInput.addEventListener("change", (e) => crcCvHandleFile(e.target.files && e.target.files[0]));
      if (analyseText && textArea) {
        analyseText.addEventListener("click", () => crcCvAnalyseText(textArea.value, "pasted CV text"));
      }
      if (drop) {
        ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
          e.preventDefault(); drop.classList.add("is-drag");
        }));
        ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
          e.preventDefault(); drop.classList.remove("is-drag");
        }));
        drop.addEventListener("drop", (e) => {
          const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          crcCvHandleFile(file);
        });
      }

      const row = document.getElementById("cv-sample-row");
      if (row) {
        row.innerHTML = "";
        cvSamples.forEach((cv) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "cv-sample-btn";
          btn.textContent = cv.name;
          btn.addEventListener("click", () => crcCvAnalyseText(cv.text, `synthetic sample "${cv.name}"`));
          row.appendChild(btn);
        });
      }
    }

    async function init() {
      const [data, cvIndexData, cvSampleData] = await Promise.all([
        fetchLocalJson("data/career_reality.json"),
        fetchLocalJson("data/cv_match_index.json"),
        fetchLocalJson("data/sample_cvs.json")
      ]);
      crcInitSection(data);
      crcCvInit(cvIndexData, cvSampleData);
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
