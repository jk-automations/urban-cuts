// Real-browser end-to-end run of the FREE draft app: open workflows/urban-cuts-draft.json in the ComfyUI frontend in
// App Mode, press Run with consent OFF (must stop at the consent gate), tick the consent switch like a user, press Run
// again, wait for the reel, screenshot the result. Any /prompt that contains a partner (paid) node is aborted, so this
// can never spend money.
// node tools/e2e_draft.mjs <comfy_url> <workflow.json> <screenshot.png>
import { chromium } from "playwright";
import fs from "fs";

const [url, wfPath, shot] = process.argv.slice(2);
const wf = JSON.parse(fs.readFileSync(wfPath, "utf8"));
const PAID = ["KlingTryOnNode", "GeminiNanoBanana2V2", "KlingVideoNode", "SoniloTextToMusic", "KlingOmniProImageToVideoNode"];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
const errors = [];
const queued = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.route("**/prompt", async (r) => {
  if (r.request().method() !== "POST") return r.continue();
  const body = JSON.parse(r.request().postData() || "{}");
  const paid = Object.values(body.prompt || {}).filter((n) => PAID.includes(n.class_type));
  if (paid.length) { console.log("ABORT: paid node in prompt"); return r.abort(); }
  const resp = await r.fetch(); queued.push((await resp.json()).prompt_id); return r.fulfill({ response: resp });
});
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.waitForFunction(() => window.app && window.app.graph, null, { timeout: 120000 });
await page.evaluate(async (w) => { await window.app.loadGraphData(w, true, true, "urban-cuts-draft"); }, wf);
await page.waitForTimeout(3000);
try { await page.click("text=Skip", { timeout: 4000 }); } catch {}

async function runAndWait(label) {
  const before = queued.length;
  const t0 = Date.now();
  await page.getByRole("button", { name: "Run", exact: true }).last().click();
  while (Date.now() - t0 < 600000) {
    await page.waitForTimeout(2000);
    const pid = queued[before];
    if (!pid) continue;
    const h = await (await fetch(`${url}/history/${pid}`)).json();
    if (h[pid] && h[pid].status && h[pid].status.completed !== undefined) {
      const err = (h[pid].status.messages || []).filter((m) => m[0] === "execution_error").map((m) => m[1].exception_message.slice(0, 80));
      const res = { run: label, prompt_id: pid, status: h[pid].status.status_str, seconds: Math.round((Date.now() - t0) / 1000), error: err[0] || null };
      console.log(JSON.stringify(res)); return res;
    }
  }
  return { run: label, status: "timeout" };
}

const consentValue = () => page.evaluate(() => window.app.graph.nodes.find((n) => n.type === "UrbanBrief").widgets.find((w) => w.name === "consent").value);
console.log("consent before:", await consentValue());
const blocked = await runAndWait("consent off");
await page.waitForTimeout(1500);
// tick the consent switch in the App Mode form (the first switch; the other one is the AI label)
await page.getByRole("switch").first().click();
await page.waitForTimeout(500);
console.log("consent after click:", await consentValue());
// type a headline like a user (also makes this a fresh render, not a cache hit of an earlier run)
const headline = process.env.HEADLINE || `New arrivals ${new Date().toISOString().slice(11, 19)}`;
const box = page.locator("text=Headline on the first look").locator("xpath=following::input[1] | following::textarea[1]").first();
await box.fill(headline); await box.press("Tab");
await page.waitForTimeout(500);
const ok = await runAndWait("consent on");
await page.waitForTimeout(5000);
await page.screenshot({ path: shot });
const hist = await (await fetch(`${url}/history/${ok.prompt_id}`)).json();
const files = Object.values(hist[ok.prompt_id].outputs).flatMap((o) => [...(o.images || []), ...(o.videos || [])]).map((f) => `${f.type}/${f.subfolder}/${f.filename}`);
console.log("outputs:", JSON.stringify(files));
// open the reel in the result viewer and screenshot it too
try { await page.locator("video").first().scrollIntoViewIfNeeded(); } catch {}
try { await page.mouse.click(618, 1553);   // the reel thumbnail in the results strip
   await page.waitForTimeout(2500); await page.screenshot({ path: shot.replace(/\.png$/, "-reel.png") }); } catch {}
const vids = await page.evaluate(() => [...document.querySelectorAll("video")].map((v) => v.currentSrc || v.src));
console.log(JSON.stringify({ blocked_ok: blocked.status === "error" && /consent/.test(blocked.error || ""), success: ok.status === "success",
  videos_on_page: vids.length, page_errors: errors.slice(0, 3) }));
await browser.close();
