import {test,expect} from '@playwright/test';import fs from 'node:fs';
test('CONTROL: real TCP torrent, Russian stream, playback, far seek, switch and ended',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await expect(page.locator('#connection')).toHaveText('Исполнитель доступен');
 await page.locator('#episode').selectOption('2');await page.locator('#search').click();
 await expect(page.locator('#count')).toHaveText('1',{timeout:35000});await page.locator('#auto').click();
 await expect.poll(()=>page.locator('video').evaluate(v=>({time:v.currentTime,ready:v.readyState})),{timeout:160000}).toMatchObject({ready:4});
 await page.locator('video').evaluate(v=>{v.muted=true;return v.play()});await expect.poll(()=>page.locator('video').evaluate(v=>v.currentTime),{timeout:60000}).toBeGreaterThan(1);
 await expect(page.locator('#audio')).toContainText('CONTROL RU');expect(await page.locator('#audio').inputValue()).toBe('2');
 const initial=await page.locator('video').evaluate(v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight,frames:v.getVideoPlaybackQuality().totalVideoFrames,buffered:[...Array(v.buffered.length)].map((_,i)=>[v.buffered.start(i),v.buffered.end(i)])}));
 expect(initial.duration).toBeGreaterThan(149);expect(initial.frames).toBeGreaterThan(0);expect(initial.buffered.at(-1)[1]).toBeLessThan(120);
 await page.locator('video').evaluate(v=>v.currentTime=120);
 await expect.poll(()=>page.locator('video').evaluate(v=>v.currentTime),{timeout:150000}).toBeGreaterThan(121);
 const far=await page.locator('video').evaluate(v=>({time:v.currentTime,ready:v.readyState,frames:v.getVideoPlaybackQuality().totalVideoFrames}));
 await page.locator('#audio').selectOption('1');
 await expect.poll(()=>page.locator('video').evaluate(v=>v.currentTime),{timeout:150000}).toBeGreaterThan(123);
 await page.locator('video').evaluate(v=>v.currentTime=147.5);
 await expect.poll(()=>page.locator('video').evaluate(v=>v.ended),{timeout:150000}).toBeTruthy();
 expect(errors).toEqual([]);expect(await page.locator('iframe').count()).toBe(0);
 const report={kind:'CONTROL_REAL_TCP_TORRENT_BROWSER',platform:'Chromium Linux; not physical iPhone',search:'SYNTHETIC',media:'OWNED_GENERATED_150S',initial,far,ended:true,commercialTitlesVerified:false,errors,
  events:await page.evaluate(()=>JSON.parse(localStorage.getItem('test-video.log.v1')||'[]'))};
 fs.mkdirSync('evidence',{recursive:true});fs.writeFileSync('evidence/browser-control.json',JSON.stringify(report,null,2));await page.screenshot({path:'evidence/browser-control.png',fullPage:true});
});
