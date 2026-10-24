import {build} from 'vite';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
const sha=process.env.VERCEL_GIT_COMMIT_SHA||process.env.GITHUB_SHA||execFileSync('git',['rev-parse','HEAD']).toString().trim();
await build({base:'./',define:{__BUILD_SHA__:JSON.stringify(sha)},server:{proxy:{'/api':'http://127.0.0.1:8000'}}});
fs.writeFileSync('dist/build-info.json',JSON.stringify({version:'torrent-1',sha,builtAt:new Date().toISOString(),transport:'torrent-only',iframe:false}));
