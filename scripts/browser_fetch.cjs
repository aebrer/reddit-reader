#!/usr/bin/env node
// Render public Reddit HTML when the JSON endpoints and Redlib are blocked.
const { chromium } = require('playwright');

function pageIsReady(id) {
  // Reddit's JavaScript challenge navigates again after DOMContentLoaded.
  if (!document.body) return false;
  if (document.body.innerText.includes("You've been blocked by network security")) {
    return true;
  }
  const post = document.querySelector('shreddit-post');
  if (!post) return false;
  if (id) {
    return !!document.querySelector(`shreddit-comment[thingid="t1_${id}"] [slot="comment"]`);
  }
  return !!document.querySelector('shreddit-comment [slot="comment"]') ||
    post.getAttribute('comment-count') === '0';
}

async function main() {
  const url = new URL(process.argv[2]);
  if (url.protocol !== 'https:' || url.hostname !== 'www.reddit.com') {
    throw new Error('Browser fallback only accepts https://www.reddit.com URLs');
  }
  const commentId = url.pathname.match(/\/comments\/\w+\/[^/]*\/(\w+)\/?$/)?.[1];
  // The newer single-comment UI hides replies behind lazy-load buttons. The
  // legacy tree renders the requested comment, ancestors, and replies together.
  if (commentId) url.searchParams.set('force-legacy-sct', '1');

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      // Reddit blocks the default HeadlessChrome user agent.
      userAgent: `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${browser.version()} Safari/537.36`,
    });
    const page = await context.newPage();
    await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForFunction(pageIsReady, commentId, { timeout: 30000 });
    if (!await page.locator('shreddit-post').count()) {
      throw new Error('Reddit blocked the browser request');
    }
    // Keep structured HTML, not innerText: parentid/thingid retain threading.
    process.stdout.write(await page.content());
  } finally {
    await browser.close();
  }
}

module.exports = { pageIsReady };
if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
