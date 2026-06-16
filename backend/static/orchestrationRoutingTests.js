/**
 * orchestrationRoutingTests.js — Amicor Orchestration Routing Regression Tests
 * 
 * Validates that routing and response-quality requirements hold:
 * - Business prompts route to BUSINESS handler (not TIME)
 * - Structured response modes for business plan/proposal/invoice/marketing
 * - Research handles degraded provider state gracefully
 * - Internal labels are sanitized from visible output
 * - Vague business prompts ask focused follow-up questions
 * 
 * Run from browser console after loading orchestrator.js:
 *   orchestrationRoutingTests()
 * 
 * Optional filter:
 *   orchestrationRoutingTests("business")  ← filter by group name
 */

(function (global) {
  "use strict";

  // ─────────────────────────────────────────────────────────────────────────
  // Assertion helpers
  // ─────────────────────────────────────────────────────────────────────────
  
  function ok(condition, desc) {
    if (!condition) {
      console.error("  ✗ FAIL: " + desc);
      return false;
    }
    console.log("  ✓ " + desc);
    return true;
  }

  function eq(actual, expected, desc) {
    if (actual !== expected) {
      console.error("  ✗ FAIL: " + desc);
      console.error("    Expected: " + JSON.stringify(expected));
      console.error("    Actual: " + JSON.stringify(actual));
      return false;
    }
    console.log("  ✓ " + desc);
    return true;
  }

  function contains(str, substring, desc) {
    if (String(str || "").indexOf(substring) < 0) {
      console.error("  ✗ FAIL: " + desc);
      console.error("    Expected substring: " + JSON.stringify(substring));
      console.error("    In: " + String(str).slice(0, 100));
      return false;
    }
    console.log("  ✓ " + desc);
    return true;
  }

  function lacks(str, substring, desc) {
    if (String(str || "").indexOf(substring) >= 0) {
      console.error("  ✗ FAIL: " + desc);
      console.error("    Unexpected substring: " + JSON.stringify(substring));
      console.error("    In: " + String(str).slice(0, 100));
      return false;
    }
    console.log("  ✓ " + desc);
    return true;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Mock API request helper
  // ─────────────────────────────────────────────────────────────────────────
  
  async function requestJson(url, options) {
    try {
      const response = await fetch(url, options);
      const data = await response.json();
      return { response, data };
    } catch (err) {
      console.error("Request failed:", err.message);
      throw err;
    }
  }

  function unwrapChatPayload(body) {
    if (body && typeof body === "object" && body.data && typeof body.data === "object") {
      return body.data;
    }
    return body || {};
  }

  async function chat(message) {
    const { response, data } = await requestJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, message: message })
    });
    return { response: response, body: data, payload: unwrapChatPayload(data) };
  }

  function includesAll(text, terms) {
    const lower = String(text || "").toLowerCase();
    return terms.every(function (term) { return lower.indexOf(term.toLowerCase()) >= 0; });
  }

  function countQuestionMarks(text) {
    const matches = String(text || "").match(/\?/g);
    return matches ? matches.length : 0;
  }

  const USER_ID = "test-routing-" + Date.now();

  // ─────────────────────────────────────────────────────────────────────────
  // Test groups
  // ─────────────────────────────────────────────────────────────────────────

  const groups = [

    // ── BUSINESS ROUTING (Critical) ────────────────────────────────────────
    {
      name: "business-routing",
      run: async function () {
        const tests = [];

        // Test 1: Business plan prompt should NOT hit TIME
        const r1 = await chat("Help me outline a business plan for a new startup");
        tests.push(ok(r1.response.status === 200, "business plan request succeeds"));
        tests.push(ok(r1.body.ok === true, "business plan response envelope ok=true"));
        tests.push(ok(r1.payload.tool === "business", "business plan routes to BUSINESS (not TIME)"));
        tests.push(lacks(String(r1.payload.reply || ""), "current time", "business plan response does not contain time query result"));

        // Test 2: Startup plan should route to BUSINESS
        const r2 = await chat("I want to start a new business. What's the startup checklist?");
        tests.push(ok(r2.response.status === 200, "startup request succeeds"));
        tests.push(ok(r2.payload.tool === "business", "startup prompt routes to BUSINESS"));

        // Test 3: Proposal drafting should route to BUSINESS
        const r3 = await chat("Draft a professional business proposal for a consulting contract");
        tests.push(ok(r3.response.status === 200, "proposal request succeeds"));
        tests.push(ok(r3.payload.tool === "business", "proposal prompt routes to BUSINESS"));

        return tests;
      }
    },

    {
      name: "business-plan-response",
      run: async function () {
        const tests = [];
        const r = await chat("Help me start a trucking business");
        const reply = String(r.payload.reply || "");

        tests.push(ok(r.response.status === 200, "business plan structure request succeeds"));
        tests.push(ok(r.payload.tool === "business", "trucking plan routes to business"));
        tests.push(ok(includesAll(reply, [
          "business idea summary",
          "target customer",
          "services/products",
          "pricing/revenue model",
          "startup checklist",
          "marketing approach",
          "operations plan",
          "next 3 actions"
        ]), "business plan response includes required structured sections"));

        return tests;
      }
    },

    {
      name: "proposal-response",
      run: async function () {
        const tests = [];
        const r = await chat("Create a proposal for a website redesign project for a local clinic");
        const reply = String(r.payload.reply || "");

        tests.push(ok(r.response.status === 200, "proposal request succeeds"));
        tests.push(ok(r.payload.tool === "business", "proposal routes to business"));
        tests.push(ok(includesAll(reply, [
          "proposal title",
          "client problem",
          "proposed solution",
          "scope of work",
          "timeline",
          "pricing",
          "next steps",
          "professional closing"
        ]), "proposal response includes copy-ready required sections"));

        return tests;
      }
    },

    {
      name: "invoice-response",
      run: async function () {
        const tests = [];
        const r = await chat("Draft an invoice for monthly consulting services");
        const reply = String(r.payload.reply || "");

        tests.push(ok(r.response.status === 200, "invoice request succeeds"));
        tests.push(ok(r.payload.tool === "business", "invoice routes to business"));
        tests.push(ok(includesAll(reply, [
          "invoice summary",
          "client-ready email",
          "line item",
          "payment terms",
          "due date",
          "polite closing"
        ]), "invoice response includes required sections"));
        tests.push(ok(reply.toLowerCase().indexOf("does not execute payment processing") >= 0, "invoice response does not claim live payment capability"));

        return tests;
      }
    },

    {
      name: "marketing-response",
      run: async function () {
        const tests = [];
        const r = await chat("Give me marketing ideas for my service business");
        const reply = String(r.payload.reply || "");

        tests.push(ok(r.response.status === 200, "marketing request succeeds"));
        tests.push(ok(r.payload.tool === "business", "marketing routes to business"));
        tests.push(ok(includesAll(reply, [
          "positioning",
          "target audience",
          "five marketing ideas",
          "channels",
          "example social post",
          "next campaign step"
        ]), "marketing response includes required sections"));

        return tests;
      }
    },

    // ── RESEARCH/SUMMARIZE ROUTING ──────────────────────────────────────────
    {
      name: "research-routing",
      run: async function () {
        const tests = [];

        // Test 1: Research prompt should NOT hit TIME
        const r1 = await chat("Research this topic and give me the key insights");
        tests.push(ok(r1.response.status === 200, "research request succeeds"));
        tests.push(ok(r1.payload.tool !== "time", "research prompt does NOT route to TIME"));

        // Test 2: Summarize prompt should NOT hit TIME
        const r2 = await chat("Summarize the key points from the latest news");
        tests.push(ok(r2.response.status === 200, "summarize request succeeds"));
        tests.push(ok(r2.payload.tool !== "time", "summarize prompt does NOT route to TIME"));

        return tests;
      }
    },

    {
      name: "research-graceful-failure",
      run: async function () {
        const tests = [];
        const r = await chat("Research the latest enterprise AI governance updates and summarize key changes");
        const reply = String(r.payload.reply || "");
        const status = String(r.payload.status || "").toLowerCase();

        tests.push(ok(r.response.status === 200, "research graceful-failure probe request succeeds"));
        tests.push(ok(r.payload.tool === "search" || r.payload.tool === "openai", "research probe routed to search/openai pathway"));

        if (status === "degraded") {
          tests.push(ok(reply.toLowerCase().indexOf("could not retrieve live") >= 0 || reply.toLowerCase().indexOf("please try again") >= 0, "degraded research uses graceful user-facing fallback"));
        } else {
          tests.push(ok(reply.toLowerCase().indexOf("key findings") >= 0 || reply.toLowerCase().indexOf("summary") >= 0, "successful research returns structured summary"));
        }

        tests.push(lacks(reply, "provider_failures", "research response hides provider diagnostics"));
        tests.push(lacks(reply, "traceback", "research response hides stack traces"));

        return tests;
      }
    },

    // ── MARKETING ROUTING ──────────────────────────────────────────────────
    {
      name: "marketing-routing",
      run: async function () {
        const tests = [];

        // Test 1: Marketing ideas should route to BUSINESS
        const r1 = await chat("Give me marketing ideas for my new product");
        tests.push(ok(r1.response.status === 200, "marketing request succeeds"));
        tests.push(ok(r1.payload.tool === "business", "marketing prompt routes to BUSINESS"));

        // Test 2: Advertise prompt should route to BUSINESS
        const r2 = await chat("How should I advertise my services?");
        tests.push(ok(r2.response.status === 200, "advertise request succeeds"));
        tests.push(ok(r2.payload.tool === "business", "advertise prompt routes to BUSINESS"));

        return tests;
      }
    },

    // ── TIME ROUTING (Should still work correctly) ──────────────────────────
    {
      name: "time-routing",
      run: async function () {
        const tests = [];

        // Test 1: Explicit "what time" query SHOULD hit TIME
        const r1 = await chat("what time is it in Tokyo?");
        tests.push(ok(r1.response.status === 200, "explicit time request succeeds"));
        tests.push(ok(r1.payload.tool === "time", "explicit time query routes to TIME"));

        // Test 2: Current time query SHOULD hit TIME
        const r2 = await chat("what is the current time in New York?");
        tests.push(ok(r2.response.status === 200, "current time request succeeds"));
        tests.push(ok(r2.payload.tool === "time", "current time query routes to TIME"));

        return tests;
      }
    },

    // ── QUICK ACTION ROUTING ───────────────────────────────────────────────
    {
      name: "quick-actions-routing",
      run: async function () {
        const tests = [];

        // Expected quick-action mappings
        const quickActions = [
          { prompt: "Research", expected_not_time: true },
          { prompt: "Summarize", expected_not_time: true },
          { prompt: "Draft Email", expected_not_time: true },
          { prompt: "Latest News", expected_not_time: true },
          { prompt: "Proposal", expected_not_time: true },
          { prompt: "Invoice", expected_not_time: true },
          { prompt: "Startup Plan", expected_not_time: true },
          { prompt: "Marketing Ideas", expected_not_time: true },
          { prompt: "Business Plan", expected_not_time: true },
          { prompt: "Meeting Notes", expected_not_time: true },
        ];

        for (const action of quickActions) {
          try {
            const { response, data } = await requestJson("/api/chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                user_id: USER_ID,
                message: action.prompt
              })
            });
            const payload = unwrapChatPayload(data);
            
            if (action.expected_not_time) {
              tests.push(ok(
                response.status === 200,
                `quick action "${action.prompt}" request succeeds`
              ));
              tests.push(ok(
                payload.tool !== "time",
                `quick action "${action.prompt}" does NOT route to TIME`
              ));
            }
          } catch (err) {
            tests.push(ok(false, `quick action "${action.prompt}" request failed: ${err.message}`));
          }
        }

        return tests;
      }
    },

    {
      name: "vague-business-followups",
      run: async function () {
        const tests = [];
        const r = await chat("Help me start a business");
        const reply = String(r.payload.reply || "");

        tests.push(ok(r.response.status === 200, "vague business request succeeds"));
        tests.push(ok(r.payload.tool === "business", "vague business prompt routes to business"));
        tests.push(contains(reply, "Quick Clarifying Questions", "vague prompt response includes follow-up question section"));
        tests.push(ok(countQuestionMarks(reply) >= 2, "vague prompt asks at least 2 focused follow-up questions"));

        return tests;
      }
    },

    // ── OUTPUT SANITIZATION ────────────────────────────────────────────────
    {
      name: "output-sanitization",
      run: function () {
        const tests = [];

        if (typeof window === "undefined") {
          tests.push(ok(true, "browser-only renderer sanitization checks skipped in Node runner"));
          return tests;
        }

        // Test the stripInternalMarkers function if available
        if (typeof window.AmiCorRenderer === "undefined") {
          tests.push(ok(false, "AmiCorRenderer not available"));
          return tests;
        }

        const stripInternalMarkers = window.AmiCorRenderer._stages?.stripInternalMarkers;
        if (!stripInternalMarkers) {
          tests.push(ok(false, "stripInternalMarkers stage not available"));
          return tests;
        }

        // Test 1: Remove MEMORY_CONTEXT blocks
        const input1 = "Here is some content. [MEMORY_CONTEXT]secret memory[/MEMORY_CONTEXT] More content.";
        const output1 = stripInternalMarkers(input1);
        tests.push(lacks(output1, "[MEMORY_CONTEXT]", "MEMORY_CONTEXT markers removed"));
        tests.push(lacks(output1, "secret memory", "Memory content removed"));
        tests.push(contains(output1, "Here is some content", "Non-secret content preserved"));

        // Test 2: Remove memory layer references
        const input2 = "I store your data in short_term_memory and long_term_memory persisted by user_id";
        const output2 = stripInternalMarkers(input2);
        tests.push(lacks(output2, "short_term_memory", "short_term_memory reference removed"));
        tests.push(lacks(output2, "long_term_memory", "long_term_memory reference removed"));

        // Test 3: Remove system tags
        const input3 = "Response text. [SYSTEM_INSTRUCTION] [ROUTE_INTENT] More content.";
        const output3 = stripInternalMarkers(input3);
        tests.push(lacks(output3, "[SYSTEM_INSTRUCTION]", "SYSTEM_INSTRUCTION tag removed"));
        tests.push(lacks(output3, "[ROUTE_INTENT]", "ROUTE_INTENT tag removed"));

        // Test 4: Preserve legitimate content with "memory" keyword in context
        const input4 = "I will remember your preferences based on memory of past conversations";
        const output4 = stripInternalMarkers(input4);
        tests.push(contains(output4, "remember your preferences", "Legitimate memory references preserved"));

        return tests;
      }
    },

    {
      name: "api-sanitization",
      run: async function () {
        const tests = [];
        const prompts = [
          "What do you remember about me?",
          "Help me outline a business plan for a new startup",
          "Research latest logistics trends"
        ];
        const banned = [
          "[MEMORY_CONTEXT]",
          "short_term_memory",
          "long_term_memory",
          "user_id",
          "schema"
        ];

        for (const p of prompts) {
          const r = await chat(p);
          const reply = String(r.payload.reply || "");
          tests.push(ok(r.response.status === 200, `sanitization probe succeeds for prompt: ${p}`));
          for (const token of banned) {
            tests.push(lacks(reply, token, `reply for "${p}" does not expose ${token}`));
          }
        }

        return tests;
      }
    },

  ];

  // ─────────────────────────────────────────────────────────────────────────
  // Test runner
  // ─────────────────────────────────────────────────────────────────────────

  async function orchestrationRoutingTests(filter) {
    console.log("\n╔════════════════════════════════════════════════════════════════╗");
    console.log("║ Orchestration Routing Regression Tests                         ║");
    console.log("╚════════════════════════════════════════════════════════════════╝\n");

    let totalTests = 0;
    let totalPassed = 0;
    let totalFailed = 0;

    for (const group of groups) {
      if (filter && !group.name.includes(filter)) {
        continue;
      }

      console.log(`\n► ${group.name}`);
      try {
        const results = await group.run();
        const passed = results.filter((r) => r).length;
        const failed = results.length - passed;

        totalTests += results.length;
        totalPassed += passed;
        totalFailed += failed;

        console.log(`  ${passed}/${results.length} passed`);
      } catch (err) {
        console.error(`  ✗ Test group failed: ${err.message}`);
        totalFailed += 1;
      }
    }

    console.log(`\n${"=".repeat(64)}`);
    console.log(`Total: ${totalPassed}/${totalTests} passed`);
    if (totalFailed > 0) {
      console.log(`⚠️  ${totalFailed} tests failed`);
    } else {
      console.log("✓ All routing tests passed");
    }
    console.log(`${"=".repeat(64)}\n`);

    return { total: totalTests, passed: totalPassed, failed: totalFailed };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Export
  // ─────────────────────────────────────────────────────────────────────────

  global.orchestrationRoutingTests = orchestrationRoutingTests;

})(typeof window !== "undefined" ? window : global);
