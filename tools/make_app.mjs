// Turn the API-format graph into a normal ComfyUI workflow with App Mode set up, using ComfyUI's own frontend (so the
// saved file is exactly what the editor writes). Then reload it in a fresh browser, check it opens in App Mode and
// screenshot it as proof. Nothing is queued: POST /prompt is blocked (the partner nodes in the main graph cost money).
// node tools/make_app.mjs <comfy_url> <api.json> <out_workflow.json> <screenshot.png>   (needs the playwright package)
import { chromium } from "playwright";
import fs from "fs";

const [url, apiPath, outPath, shot] = process.argv.slice(2);
const api = JSON.parse(fs.readFileSync(apiPath, "utf8"));
const ids = (cls) => Object.entries(api).filter(([, n]) => n.class_type === cls).map(([k]) => k).sort((a, b) => a - b);
const titled = (t) => (Object.entries(api).find(([, n]) => n._meta && n._meta.title === t) || [null])[0];
const draft = ids("KlingVideoNode").length === 0;
const brief = ids("UrbanBrief")[0];
const person = titled("Person photo");
const items = [1, 2, 3, 4, 5].map((k) => titled(`Outfit or product ${k}`));
const lookPhotos = draft ? [1, 2, 3, 4, 5].map((k) => titled(`Look photo ${k}`)) : [];
const upload = titled("Your music");
const logo = titled("Logo (optional)");
// What a user sees in App Mode. Everything else stays locked in the graph.
const INPUTS = [
  [person, "image"], [brief, "consent"], [brief, "mode"], [brief, "vibe"],
  ...items.map((n) => [n, "image"]), ...lookPhotos.map((n) => [n, "image"]),
  ...(draft ? [] : [[brief, "look_engine"], [brief, "music_source"], [brief, "music_prompt"]]), [upload, "audio"],
  [brief, "look_labels"], [brief, "brand_name"], [brief, "handle"], [brief, "cta"], [logo, "image"],
  [brief, "length"], [brief, "aspect"], [brief, "angles"], [brief, "hook"], [brief, "glowup"], [brief, "pulse"], [brief, "lineup"], [brief, "headline"], [brief, "ai_label"],
];
const OUTPUTS = [titled("Your reel"), titled("Contact sheet"), titled("Receipt"), titled("Beats")];
const LABELS = { consent: "I have this person's consent to use their photo", mode: "Outfits or products", vibe: "Vibe",
  look_engine: "Try-on engine", music_source: "Music", music_prompt: "Music prompt (Sonilo; empty = vibe default)",
  length: "Length (seconds)", aspect: "Aspect", headline: "Headline on the first look (optional)", ai_label: "AI label (keep on)",
  hook: "Before→after hook", lineup: "Lineup finale", glowup: "Glow-up hit on the first look", angles: "Camera angles: 360 turnaround + close-up per look", pulse: "Beat pulse",
  look_labels: "Look names + prices (one line per look: Name | $89)", brand_name: "Shop name (lineup)",
  handle: "@handle or website (lineup)", cta: "Call to action (empty = 'Comment a number to shop')" };
const NAMED = { [person]: "Person photo (full body, 9:16)", [upload]: "Your music (a track you own)", [logo]: "Logo (optional; blank = none)" };
items.forEach((n, k) => (NAMED[n] = `Outfit or product ${k + 1}${k >= 3 ? " (optional: leave blank)" : ""}`));
lookPhotos.forEach((n, k) => (NAMED[n] = `Look ${k + 1} photo (draft: person in outfit ${k + 1})`));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.route("**/prompt", (r) => (r.request().method() === "POST" ? r.abort() : r.continue()));   // never queue
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.waitForFunction(() => window.app && window.app.graph, null, { timeout: 120000 });
const wf = await page.evaluate(async ({ api, INPUTS, OUTPUTS, LABELS, NAMED, draft }) => {
  await window.app.loadApiJson(api, draft ? "urban-cuts-draft" : "urban-cuts");
  const g = window.app.graph;
  if (g.arrange) g.arrange(80);
  for (const node of g.nodes) {
    const a = api[String(node.id)];
    if (a && a._meta && a._meta.title) node.title = a._meta.title;
    // Fixed seeds: a re-run after one failed shot re-uses every finished (already paid) step from ComfyUI's cache.
    for (const w of node.widgets || []) {
      for (const x of [w, ...(w.linkedWidgets || [])]) if (x.value === "randomize" || String(x.name).endsWith("control_after_generate")) x.value = "fixed";
    }
    for (const w of node.widgets || []) {
      let lab = null;
      if (NAMED[String(node.id)] && (w.name === "image" || w.name === "audio")) lab = NAMED[String(node.id)];
      else if (INPUTS.some(([n, name]) => String(n) === String(node.id) && name === w.name)) lab = LABELS[w.name];
      if (lab) { w.label = lab; for (const inp of node.inputs || []) if (inp.widget && inp.widget.name === w.name) inp.label = lab; }
    }
  }
  const w = g.serialize();
  for (const n of w.nodes) if (Array.isArray(n.widgets_values)) n.widgets_values = n.widgets_values.map((v) => (v === "randomize" ? "fixed" : v));
  w.extra = w.extra || {};
  w.extra.linearMode = true;
  w.extra.linearData = { inputs: INPUTS.map(([n, name]) => [Number(n), name]), outputs: OUTPUTS.map(Number) };
  // which links exist (proof the partner sub-inputs such as model.images.image_1 really connected)
  const links = g.nodes.flatMap((n) => (n.inputs || []).filter((i) => i.link != null).map((i) => `${n.type}.${i.name}`));
  return { w, links };
}, { api, INPUTS, OUTPUTS, LABELS, NAMED, draft });
const randomized = wf.w.nodes.filter((n) => (n.widgets_values || []).includes("randomize")).map((n) => n.type);
console.log("seed widgets still on randomize:", JSON.stringify(randomized));
console.log(`nodes ${wf.w.nodes.length}, links ${wf.w.links.length}, app inputs ${INPUTS.length}, outputs ${OUTPUTS.length}`);
console.log("linked partner inputs:", JSON.stringify([...new Set(wf.links.filter((l) => /^(Gemini|Kling|Sonilo)/.test(l)))]));
fs.writeFileSync(outPath, JSON.stringify(wf.w, null, 1));
// Open the saved file the way a new user would: a fresh browser context (no restored tabs), then load it.
await page.close();
const page2 = await (await browser.newContext({ viewport: { width: 1440, height: 1600 } })).newPage();
page2.on("pageerror", (e) => errors.push(e.message));
await page2.route("**/prompt", (r) => (r.request().method() === "POST" ? r.abort() : r.continue()));
await page2.goto(url, { waitUntil: "load", timeout: 120000 });
await page2.waitForFunction(() => window.app && window.app.graph, null, { timeout: 120000 });
await page2.evaluate(async (w) => { await window.app.loadGraphData(w, true, true, "urban-cuts"); }, wf.w);
await page2.waitForTimeout(4000);
const nodesNow = await page2.evaluate(() => window.app.graph.nodes.length);
const missing = await page2.evaluate(() => window.app.graph.nodes.filter((n) => n.has_errors || n.type === undefined).map((n) => n.type));
try { await page2.click("text=Skip", { timeout: 5000 }); } catch {}   // first-visit App Mode tour
await page2.waitForTimeout(1500);
const text = await page2.evaluate(() => document.body.innerText);
const inApp = /consent/.test(text) && /Outfit or product 1/.test(text);
await page2.screenshot({ path: shot });
console.log("reloaded nodes", nodesNow, "missing/error nodes", JSON.stringify(missing), "app mode form visible", inApp, "page errors", errors.length, JSON.stringify(errors.slice(0, 3)));
console.log(text.replace(/\n+/g, " | ").slice(0, 1800));
await browser.close();
