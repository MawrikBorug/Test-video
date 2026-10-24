import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'tests/browser',workers:1,retries:0,timeout:240000,
 use:{baseURL:process.env.TEST_BASE_URL||'http://127.0.0.1:5173',viewport:{width:390,height:844},trace:'off',launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||'/usr/bin/chromium',args:['--no-sandbox']}}});
