const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const attendance = require('./attendance');
const ROOT = __dirname, PUBLIC = path.join(ROOT, 'public'), DATA = path.join(ROOT, 'data/content.json'), UPLOADS = path.join(ROOT, 'uploads');
const PORT = process.env.PORT || 3000;
const ADMIN_USER = process.env.ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ADMIN_PASS || '';
const sessions = new Map();
fs.mkdirSync(UPLOADS,{recursive:true});
function readData(){ return JSON.parse(fs.readFileSync(DATA,'utf8')); }
function writeData(d){ fs.writeFileSync(DATA, JSON.stringify(d,null,2)); }
function send(res,status,body,type='application/json; charset=utf-8'){res.writeHead(status,{'Content-Type':type,'Access-Control-Allow-Origin':'*'});res.end(type.startsWith('application/json')?JSON.stringify(body):body);}
function bodyJson(req){return new Promise((resolve,reject)=>{let raw='';req.on('data',c=>{raw+=c;if(raw.length>12*1024*1024){reject(new Error('Request too large'));req.destroy();}});req.on('end',()=>{try{resolve(JSON.parse(raw||'{}'));}catch(e){reject(e);}});});}
function sessionFor(req){const token=(req.headers.authorization||'').replace(/^Bearer\s+/i,'');const session=sessions.get(token);if(!session)return null;if(session.expiresAt<Date.now()){sessions.delete(token);return null;}return session;}
function authorized(req){return sessionFor(req)?.role==='admin';}
function safeFile(name){return path.basename(name).replace(/[^a-zA-Z0-9._-]/g,'_');}
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,`http://${req.headers.host||'localhost'}`); const p=url.pathname;
  if(req.method==='OPTIONS'){res.writeHead(204,{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'Content-Type, Authorization','Access-Control-Allow-Methods':'GET,POST,PUT,DELETE,OPTIONS'});return res.end();}
  try{
    if(p==='/api/content'&&req.method==='GET'){const d=readData();return send(res,200,{settings:d.settings,services:d.services.filter(s=>s.active),gallery:d.gallery});}
    if(p==='/api/enquiries'&&req.method==='POST'){const b=await bodyJson(req);if(!b.name||!b.mobile||!b.service)return send(res,400,{error:'Name, mobile and service are required.'});const d=readData();const item={id:crypto.randomUUID(),name:String(b.name).slice(0,100),email:String(b.email||'').slice(0,150),mobile:String(b.mobile).slice(0,30),service:String(b.service).slice(0,100),message:String(b.message||'').slice(0,1000),date:new Date().toISOString()};d.enquiries.unshift(item);writeData(d);return send(res,201,{ok:true,enquiry:item,settings:d.settings});}
    if(p==='/api/admin/login'&&req.method==='POST'){const b=await bodyJson(req);const supplied=Buffer.from(String(b.password||''));const expected=Buffer.from(ADMIN_PASS);if(!ADMIN_PASS||b.username!==ADMIN_USER||supplied.length!==expected.length||!crypto.timingSafeEqual(supplied,expected))return send(res,401,{error:ADMIN_PASS?'Invalid username or password':'Admin login is not configured. Set ADMIN_USER and ADMIN_PASS, then restart the server.'});const token=crypto.randomBytes(32).toString('hex');sessions.set(token,{role:'admin',expiresAt:Date.now()+12*60*60*1000});return send(res,200,{token});}
    if(p==='/api/admin/logout'&&req.method==='POST'){const token=(req.headers.authorization||'').replace(/^Bearer\s+/i,'');sessions.delete(token);return send(res,200,{ok:true});}
    if(await attendance.handle(req,res,url,sessions))return;
    if(p.startsWith('/api/admin/')){
      if(!authorized(req))return send(res,401,{error:'Please log in as admin.'});
      if(p==='/api/admin/content'&&req.method==='GET')return send(res,200,readData());
      if(p==='/api/admin/upload'&&req.method==='POST'){const b=await bodyJson(req);const m=String(b.data||'').match(/^data:image\/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=]+)$/);if(!m)return send(res,400,{error:'Please choose a JPG, PNG or WebP image.'});const ext=m[1]==='jpeg'?'jpg':m[1];const name=crypto.randomUUID()+'.'+ext;const bytes=Buffer.from(m[2],'base64');if(bytes.length>8*1024*1024)return send(res,413,{error:'Image must be smaller than 8 MB.'});fs.writeFileSync(path.join(UPLOADS,name),bytes);return send(res,201,{url:'/uploads/'+name});}
      if(p==='/api/admin/settings'&&req.method==='PUT'){const b=await bodyJson(req),d=readData();d.settings={...d.settings,...b};writeData(d);return send(res,200,{ok:true,settings:d.settings});}
      if(p==='/api/admin/services'&&req.method==='POST'){const b=await bodyJson(req),d=readData();if(!b.name)return send(res,400,{error:'Service name is required'});const item={id:crypto.randomUUID(),name:String(b.name).slice(0,120),description:String(b.description||'').slice(0,1000),image:String(b.image||''),active:true};d.services.unshift(item);writeData(d);return send(res,201,item);}
      const serviceUpdateMatch=p.match(/^\/api\/admin\/services\/([^/]+)$/);if(serviceUpdateMatch&&req.method==='PUT'){const b=await bodyJson(req),d=readData(),item=d.services.find(x=>x.id===serviceUpdateMatch[1]);if(!item)return send(res,404,{error:'Service not found'});if(!b.name)return send(res,400,{error:'Service name is required'});item.name=String(b.name).slice(0,120);item.description=String(b.description||'').slice(0,1000);if(b.image)item.image=String(b.image);writeData(d);return send(res,200,item);}
      const serviceMatch=p.match(/^\/api\/admin\/services\/([^/]+)$/);if(serviceMatch&&req.method==='DELETE'){const d=readData();d.services=d.services.filter(x=>x.id!==serviceMatch[1]);writeData(d);return send(res,200,{ok:true});}
      if(p==='/api/admin/gallery'&&req.method==='POST'){const b=await bodyJson(req),d=readData();if(!b.title||!b.image)return send(res,400,{error:'Image title and image are required'});const item={id:crypto.randomUUID(),title:String(b.title).slice(0,120),category:String(b.category||'General').slice(0,80),image:String(b.image)};d.gallery.unshift(item);writeData(d);return send(res,201,item);}
      const galleryUpdateMatch=p.match(/^\/api\/admin\/gallery\/([^/]+)$/);if(galleryUpdateMatch&&req.method==='PUT'){const b=await bodyJson(req),d=readData(),item=d.gallery.find(x=>x.id===galleryUpdateMatch[1]);if(!item)return send(res,404,{error:'Gallery image not found'});if(!b.title)return send(res,400,{error:'Image title is required'});item.title=String(b.title).slice(0,120);item.category=String(b.category||'General').slice(0,80);if(b.image)item.image=String(b.image);writeData(d);return send(res,200,item);}
      const galleryMatch=p.match(/^\/api\/admin\/gallery\/([^/]+)$/);if(galleryMatch&&req.method==='DELETE'){const d=readData();d.gallery=d.gallery.filter(x=>x.id!==galleryMatch[1]);writeData(d);return send(res,200,{ok:true});}
      if(p==='/api/admin/enquiries'&&req.method==='GET')return send(res,200,readData().enquiries);
      return send(res,404,{error:'Admin API route not found'});
    }
    if(p.startsWith('/uploads/')){const f=path.join(UPLOADS,safeFile(p.slice('/uploads/'.length)));if(!f.startsWith(UPLOADS))return send(res,403,'Forbidden','text/plain');if(!fs.existsSync(f))return send(res,404,'Not found','text/plain');const ext=path.extname(f).toLowerCase();const type=ext==='.png'?'image/png':ext==='.webp'?'image/webp':'image/jpeg';res.writeHead(200,{'Content-Type':type});return fs.createReadStream(f).pipe(res);}
    let file=p==='/'?'index.html':p==='/attendance'?'attendance.html':p.slice(1);file=path.join(PUBLIC,path.normalize(file));if(!file.startsWith(PUBLIC))return send(res,403,'Forbidden','text/plain');if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(PUBLIC,'index.html');const ext=path.extname(file).toLowerCase();const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'};res.writeHead(200,{'Content-Type':types[ext]||'application/octet-stream','Cache-Control':'no-cache'});fs.createReadStream(file).pipe(res);
  }catch(e){console.error(e);send(res,500,{error:e.message||'Server error'});}
});
server.listen(PORT,()=>console.log(`Ecronx Manpower Website running at http://localhost:${PORT}${ADMIN_PASS?'':'\nAdmin login is disabled until ADMIN_USER and ADMIN_PASS are configured.'}`));
