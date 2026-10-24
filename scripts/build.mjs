import {build} from 'vite';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
let sha=process.env.VERCEL_GIT_COMMIT_SHA||process.env.GITHUB_SHA;
if(!sha&&fs.existsSync('source-info.json'))sha=JSON.parse(fs.readFileSync('source-info.json')).sha;
if(!sha){try{sha=execFileSync('git',['rev-parse','HEAD']).toString().trim()}catch{sha='unknown'}}
if(!fs.existsSync('node_modules/ffmpeg-static/ffmpeg'))execFileSync(process.execPath,['node_modules/ffmpeg-static/install.js'],{stdio:'inherit',cwd:process.cwd()});
fs.mkdirSync('backend/metadata',{recursive:true});
for(const item of JSON.parse(fs.readFileSync('backend/metadata-index.json'))){
 const path='backend/metadata/'+item.name;
 if(!fs.existsSync(path)){const r=await fetch(item.url);if(!r.ok)throw new Error('Metadata snapshot unavailable: '+r.status);const b=Buffer.from(await r.arrayBuffer());if(createHash('sha256').update(b).digest('hex')!==item.sha256)throw new Error('Metadata snapshot checksum mismatch');fs.writeFileSync(path,b);}
 if(createHash('sha256').update(fs.readFileSync(path)).digest('hex')!==item.sha256)throw new Error('Metadata snapshot checksum mismatch');
}
await build({base:'./',define:{__BUILD_SHA__:JSON.stringify(sha)},server:{proxy:{'/api':'http://127.0.0.1:8000'}}});
fs.writeFileSync('dist/build-info.json',JSON.stringify({version:'torrent-1',sha,builtAt:new Date().toISOString(),transport:'torrent-only',iframe:false}));
if(fs.existsSync('evidence/verification.json'))fs.copyFileSync('evidence/verification.json','dist/verification.json');
