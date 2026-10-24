import {test,expect} from '@playwright/test';
test('SYNTHETIC control: late initial verification cannot reset a user selection or cancel search',async({page})=>{
 let release;const gate=new Promise(r=>release=r);
 await page.route('**/verification.json',async route=>{await gate;await route.fulfill({json:{commercialTitlesWithVerifiedPlayback:0,requiredTitles:10,liveSearchResponsesWithCandidates:48,liveSearchRequests:48,selectionPlaybackAccepted:false,at:'2026-10-24T00:00:00Z'}})});
 await page.goto('/');await expect(page.locator('#connection')).toHaveText('Контрольный исполнитель');
 await page.locator('[data-key=deathnote]').click();await expect(page.locator('#work-title')).toContainText('Тетрадь смерти');
 await page.locator('#episode').selectOption('2');await page.locator('#search').click();release();
 await expect(page.locator('#count')).toHaveText('2',{timeout:25000});
 await expect(page.locator('#episode')).toHaveValue('2');await expect(page.locator('#work-title')).toContainText('Тетрадь смерти');
 const logs=await page.evaluate(()=>JSON.parse(localStorage.getItem('test-video.log.v1')||'[]'));
 expect(logs.some(e=>e.code==='LIVE_SEARCH'&&e.details.work==='deathnote'&&e.details.episode===2)).toBeTruthy();
});
