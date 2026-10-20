const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');

let chromium;
try {
    ({ chromium } = require('playwright'));
} catch (error) {
    throw new Error('Playwright is required. Install it with "npm install --no-save playwright" and run "npx playwright install chromium".', { cause: error });
}

const rootDirectory = __dirname;
const screenshotsDirectory = path.join(rootDirectory, 'screenshots');
const contentTypes = {
    '.html': 'text/html; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.mp3': 'audio/mpeg',
    '.svg': 'image/svg+xml'
};

function createStaticServer() {
    return http.createServer(async (request, response) => {
        if (request.method !== 'GET' && request.method !== 'HEAD') {
            response.writeHead(405, { Allow: 'GET, HEAD' });
            response.end();
            return;
        }

        let filePath;
        try {
            const requestUrl = new URL(request.url, 'http://127.0.0.1');
            const requestedPath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, '') || 'index.html';
            filePath = path.resolve(rootDirectory, requestedPath);
        } catch (error) {
            response.writeHead(400);
            response.end('Invalid request path');
            return;
        }

        const relativePath = path.relative(rootDirectory, filePath);
        if (relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
            response.writeHead(403);
            response.end('Forbidden');
            return;
        }

        try {
            const file = await fs.readFile(filePath);
            response.writeHead(200, {
                'Content-Type': contentTypes[path.extname(filePath).toLowerCase()] || 'application/octet-stream',
                'Content-Length': file.length
            });
            response.end(request.method === 'HEAD' ? undefined : file);
        } catch (error) {
            if (error.code === 'ENOENT' || error.code === 'EISDIR') {
                response.writeHead(404);
                response.end('Not found');
                return;
            }
            console.error(`Failed to serve ${filePath}:`, error);
            response.writeHead(500);
            response.end('Failed to read file');
        }
    });
}

async function listen(server) {
    await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, '127.0.0.1', resolve);
    });
    return server.address().port;
}

async function waitForServer(port) {
    const url = `http://127.0.0.1:${port}/arguments_index.json`;
    let lastError;

    for (let attempt = 0; attempt < 20; attempt++) {
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Server returned HTTP ${response.status}`);
            }

            const index = await response.json();
            if (!Array.isArray(index.arguments)) {
                throw new Error('The argument index does not contain an arguments array.');
            }
            return;
        } catch (error) {
            lastError = error;
            await new Promise(resolve => setTimeout(resolve, 250));
        }
    }

    throw new Error(`Local server did not become ready: ${lastError.message}`);
}

async function capture(page, fileName) {
    const filePath = path.join(screenshotsDirectory, fileName);
    await page.screenshot({ path: filePath, fullPage: true, animations: 'disabled' });
    console.log(`Saved ${path.relative(rootDirectory, filePath)}`);
}

async function main() {
    await fs.mkdir(screenshotsDirectory, { recursive: true });

    const server = createStaticServer();
    let browser;
    try {
        const port = await listen(server);
        await waitForServer(port);
        browser = await chromium.launch({ headless: true });
        const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

        await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'load' });
        await page.waitForFunction(() => {
            const status = document.getElementById('masterStatus');
            return window.masterMap || (status && !status.classList.contains('hidden'));
        });
        const masterStatus = await page.locator('#masterStatus').textContent();
        if (!await page.evaluate(() => Boolean(window.masterMap))) {
            throw new Error(`Master map failed to initialize: ${masterStatus.trim()}`);
        }
        await page.locator('#masterGrid .argument-card').first().waitFor({ state: 'visible' });
        await capture(page, 'full_page.png');

        await page.locator('#masterMapView [data-open-settings]').click();
        await page.locator('#settingsModal').waitFor({ state: 'visible' });
        await capture(page, 'settings-modal.png');
        await page.locator('#closeSettingsBtn').click();

        await page.locator('[data-explore-id="arg_kalam"]').click();
        await page.locator('#deepView .node-card').first().waitFor({ state: 'visible' });
        await page.locator('#viewFullBtn').click();
        await page.locator('#resetViewHeaderBtn').click();
        await page.locator('#node-1\\.0').click();
        await capture(page, 'expanded-kalam-tree.png');

        await page.locator('#addRebuttalBtn').click();
        await page.locator('#addNodeModal').waitFor({ state: 'visible' });
        await capture(page, 'add-counter-argument-modal.png');
        await page.locator('#cancelModalBtn').click();

        const playButton = page.locator('#node-1\\.0 [data-play-audio-id="1.0"]');
        await playButton.click();
        await page.waitForFunction(() => {
            const button = document.querySelector('#node-1\\.0 [data-play-audio-id="1.0"]');
            return button?.getAttribute('aria-pressed') === 'true' && button.textContent.includes('Pause');
        });
        await capture(page, 'audio_player_active.png');

        await page.locator('#backToMasterBtn').click();
        await page.locator('[data-side="theist"]').click();
        await page.waitForFunction(() => document.getElementById('masterResultCount').textContent === '40 of 75 arguments');
        await capture(page, 'filtered_state.png');

        const sandboxPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
        await sandboxPage.goto(`http://127.0.0.1:${port}/sandbox.html`, { waitUntil: 'load' });
        await sandboxPage.locator('#ttsContent').waitFor({ state: 'visible' });
        await capture(sandboxPage, 'sandbox.png');
    } finally {
        if (browser) await browser.close();
        await new Promise((resolve, reject) => {
            server.close(error => error ? reject(error) : resolve());
        });
    }
}

main().catch(error => {
    console.error('Screenshot capture failed:', error);
    process.exitCode = 1;
});
