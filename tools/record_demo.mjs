// Real screenshots of the app for the demo video, taken in the ComfyUI frontend. Nothing paid can run: every /prompt
// containing a partner node is aborted.
//   app.png        the partner app in App Mode with the demo inputs and consent ticked (Run is not pressed)
//   graph.png      the node graph behind it
//   draft-*.png    the FREE draft app with the demo looks: Run pressed, the contact sheet and the reel on screen
// node tools/record_demo.mjs <comfy_url> <out_dir>
import { chromium } from "playwright";
import fs from "fs";

const [url, outDir] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const PAID = ["KlingTryOnNode", "GeminiNanoBanana2V2", "KlingVideoNode", "SoniloTextToMusic"];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
let queued = null;
await page.route("**/prompt", async (r) => {
  if (r.request().method() !== "POST") return r.continue();
  const body = JSON.parse(r.request().postData() || "{}");
  if (Object.values(body.prompt || {}).some((n) => PAID.includes(n.class_type))) { console.log("ABORT paid prompt"); return r.abort(); }
  const resp = await r.fetch(); queued = (await resp.json()).prompt_id; return r.fulfill({ response: resp });
});
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.waitForFunction(() => window.app && window.app.graph, null, { timeout: 120000 });

const DEMO = { "Person photo": "urban_demo_model.png", "Outfit or product 1": "urban_demo_outfit_1.png",
  "Outfit or product 2": "urban_demo_outfit_2.png", "Outfit or product 3": "urban_demo_outfit_3.png",
  "Outfit or product 4": "urban_demo_outfit_4.png", "Outfit or product 5": "urban_blank.png",
  "Look photo 1": "urban_demo_look_1.png", "Look photo 2": "urban_demo_look_2.png",
  "Look photo 3": "urban_demo_look_3.png", "Look photo 4": "urban_demo_look_4.png", "Look photo 5": "urban_blank.png" };

async function load(file, { graph = false } = {}) {
  const wf = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const n of wf.nodes) if (DEMO[n.title] && n.type === "LoadImage") n.widgets_values[0] = DEMO[n.title];
  if (graph) { wf.extra.linearMode = false; }
  await page.evaluate(async (w) => { await window.app.loadGraphData(w, true, true, "urban-cuts"); }, wf);
  await page.waitForTimeout(3000);
  try { await page.click("text=Skip", { timeout: 3000 }); } catch {}
  await page.waitForTimeout(1500);
}

await load("workflows/urban-cuts.json");
await page.getByRole("switch").first().click();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${outDir}/app.png` });

await load("workflows/urban-cuts.json", { graph: true });
await page.evaluate(() => { const c = window.app.canvas; c.ds.scale = 0.42; c.ds.offset = [40, 60]; c.setDirty(true, true); });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${outDir}/graph.png` });

await load("workflows/urban-cuts-draft.json");
await page.getByRole("switch").first().click();
const box = page.locator("text=Headline on the first look").locator("xpath=following::input[1] | following::textarea[1]").first();
await box.fill(""); await box.press("Tab");
await page.waitForTimeout(800);
await page.screenshot({ path: `${outDir}/draft-form.png` });
await page.getByRole("button", { name: "Run", exact: true }).last().click();
for (let i = 0; i < 300; i++) {
  await page.waitForTimeout(1000);
  if (!queued) continue;
  const h = await (await fetch(`${url}/history/${queued}`)).json();
  if (h[queued] && h[queued].status && h[queued].status.completed !== undefined) { console.log("draft", h[queued].status.status_str, i, "s"); break; }
}
await page.waitForTimeout(5000);
try { await page.mouse.click(563, 1553); await page.waitForTimeout(2000); } catch {}   // the contact sheet thumbnail
await page.screenshot({ path: `${outDir}/draft-sheet.png` });
try { await page.mouse.click(618, 1553); await page.waitForTimeout(2500); } catch {}
await page.screenshot({ path: `${outDir}/draft-reel.png` });
await browser.close();
