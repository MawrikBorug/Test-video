import {build} from 'vite';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {gzipSync} from 'node:zlib';
async function download(url){
 if(['HTTPS_PROXY','HTTP_PROXY','https_proxy','http_proxy'].some(k=>process.env[k])){
  return execFileSync('curl',['--fail','--location','--silent','--show-error','--max-time','60',url],{maxBuffer:32*1024**2});
 }
 const r=await fetch(url);if(!r.ok)throw new Error('Build download failed: '+r.status);return Buffer.from(await r.arrayBuffer());
}
let sha=process.env.VERCEL_GIT_COMMIT_SHA||process.env.GITHUB_SHA;
if(!sha&&fs.existsSync('source-info.json'))sha=JSON.parse(fs.readFileSync('source-info.json')).sha;
if(!sha){try{sha=execFileSync('git',['rev-parse','HEAD']).toString().trim()}catch{sha='unknown'}}
let serverComponents=null;
if(process.env.VERCEL==='1'||process.env.BUNDLE_STREMIO==='1'){
 const dir='backend/runtime';fs.mkdirSync(dir,{recursive:true});
 const nodeRaw=fs.readFileSync(process.execPath),nodePacked=gzipSync(nodeRaw,{level:9});
 fs.writeFileSync(path.join(dir,'node.gz'),nodePacked);fs.rmSync(path.join(dir,'node'),{force:true});
 const probe='node_modules/ffprobe-static/bin/linux/x64/ffprobe',probePacked=path.join(dir,'ffprobe.gz');
 if(fs.existsSync(probe)){fs.writeFileSync(probePacked,gzipSync(fs.readFileSync(probe),{level:9}));fs.unlinkSync(probe);}
 if(!fs.existsSync(probePacked))throw new Error('ffprobe is missing from the function bundle');
 const source='https://dl.strem.io/server/v4.20.17/desktop/server.js';
 const digest='567a397bb11b788571bf1750fd05dd78927f97bec0c9ddeaa6d9cc1eccee3922';
 const target=path.join(dir,'stremio-server.cjs');
 if(!fs.existsSync(target)||createHash('sha256').update(fs.readFileSync(target)).digest('hex')!==digest){
  const body=await download(source);if(createHash('sha256').update(body).digest('hex')!==digest)throw new Error('Stremio checksum mismatch');fs.writeFileSync(target,body);
 }
 fs.writeFileSync(path.join(dir,'NODE_LICENSE'),await download(`https://raw.githubusercontent.com/nodejs/node/${process.version}/LICENSE`));
 serverComponents={nodeVersion:process.version,nodeBytes:nodeRaw.length,packedNodeBytes:nodePacked.length,packedFfprobeBytes:fs.statSync(probePacked).size,stremioVersion:'4.20.17',stremioSha256:digest,stremioSource:source};
 fs.writeFileSync(path.join(dir,'runtime-info.json'),JSON.stringify(serverComponents));
}
if(process.env.SKIP_BUNDLED_FFMPEG!=='1'&&!fs.existsSync('node_modules/ffmpeg-static/ffmpeg'))execFileSync(process.execPath,['node_modules/ffmpeg-static/install.js'],{stdio:'inherit',cwd:process.cwd()});
fs.mkdirSync('backend/metadata',{recursive:true});
for(const item of JSON.parse(fs.readFileSync('backend/metadata-index.json'))){
 const path='backend/metadata/'+item.name;
 if(!fs.existsSync(path)){const b=await download(item.url);if(createHash('sha256').update(b).digest('hex')!==item.sha256)throw new Error('Metadata snapshot checksum mismatch');fs.writeFileSync(path,b);}
 if(createHash('sha256').update(fs.readFileSync(path)).digest('hex')!==item.sha256)throw new Error('Metadata snapshot checksum mismatch');
}
await build({base:'./',define:{__BUILD_SHA__:JSON.stringify(sha)},server:{proxy:{'/api':'http://127.0.0.1:8000'}}});
fs.writeFileSync('dist/build-info.json',JSON.stringify({version:'torrent-1',sha,builtAt:new Date().toISOString(),transport:'torrent-only',iframe:false,serverComponents}));
if(fs.existsSync('evidence/verification.json'))fs.copyFileSync('evidence/verification.json','dist/verification.json');
