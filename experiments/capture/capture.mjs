import { chromium } from "playwright";
import { mkdir, readFile, readdir, rename, rm } from "node:fs/promises";
import { join } from "node:path";

const root = new URL(".", import.meta.url).pathname;
const videoDir = join(root, "video");
await rm(videoDir, { recursive: true, force: true });
await mkdir(videoDir, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
async function connectPage(context) {
  const page = await context.newPage();
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await page.goto("http://127.0.0.1:6080");
    try {
      await page.waitForFunction(() => document.title.includes("connected"), null, { timeout: 5000 });
      return page;
    } catch {
      await page.waitForTimeout(1000);
    }
  }
  throw new Error("noVNC did not connect after 10 attempts");
}

const controlContext = await browser.newContext({ viewport: { width: 1024, height: 768 } });
const page = await connectPage(controlContext);
await page.waitForTimeout(12000);
await page.locator("#screen").click();
await page.keyboard.type("root", { delay: 120 });
await page.keyboard.press("Enter");
await page.waitForTimeout(700);
await page.keyboard.press("Enter");
await page.waitForTimeout(2500);
await page.keyboard.type("run /inyect/experiments/xclock/xclock.sh", { delay: 65 });
await page.keyboard.press("Enter");

const serialLog = process.env.CAPTURE_SERIAL_LOG;
let clockReady = false;
for (let attempt = 0; attempt < 60 && !clockReady; attempt += 1) {
  const serial = await readFile(serialLog, "utf8").catch(() => "");
  const times = serial.match(/Time: [0-2][0-9]:[0-5][0-9]:[0-5][0-9]/g) || [];
  clockReady = times.length >= 2;
  if (!clockReady) await page.waitForTimeout(500);
}
if (!clockReady) throw new Error("clock did not render two frames before recording");
await controlContext.close();

const recordContext = await browser.newContext({
  viewport: { width: 1024, height: 768 },
  recordVideo: { dir: videoDir, size: { width: 1024, height: 768 } },
});
await connectPage(recordContext);
await new Promise((resolve) => setTimeout(resolve, 8000));
await recordContext.close();
await browser.close();

const recordings = (await readdir(videoDir)).filter((name) => name.endsWith(".webm"));
if (recordings.length === 0) throw new Error("Playwright produced no video");
await rename(join(videoDir, recordings[0]), join(root, "xclock-vnc.webm"));
console.log("captured xclock-vnc.webm");
