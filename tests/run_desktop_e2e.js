const {spawn} = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const electron = path.join(root, 'node_modules', 'electron', 'dist', 'electron.exe');
const port = 19177;
const appData = path.join(root, 'runtime', 'desktop-e2e-appdata');
fs.mkdirSync(appData, {recursive:true});

function call(token, endpoint, body={}) {
  return new Promise((resolve,reject)=>{
    const payload=Buffer.from(JSON.stringify(body));
    const request=http.request({host:'127.0.0.1',port,path:endpoint,method:'POST',headers:{'Content-Type':'application/json','Content-Length':payload.length,'X-Vibe-Automation-Token':token}},response=>{let data='';response.on('data',x=>data+=x);response.on('end',()=>{try{resolve({status:response.statusCode,value:JSON.parse(data)})}catch(error){reject(error)}})});
    request.on('error',reject);request.end(payload);
  });
}
function wait(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
async function waitBody(token, text, timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){const snap=await call(token,'/snapshot');if(snap.value.body.includes(text))return snap.value;await wait(250)}throw new Error(`Timed out waiting for ${text}`)}

async function main(){
  const child=spawn(electron,[root],{cwd:root,env:{...process.env,VIBE_AUTOMATION_PORT:String(port),APPDATA:appData},stdio:['ignore','pipe','pipe']});
  let combined='';child.stdout.on('data',x=>combined+=x);child.stderr.on('data',x=>combined+=x);
  let token='';for(let i=0;i<120&&!token;i++){const match=combined.match(/VIBE_AUTOMATION_READY \d+ ([A-Za-z0-9_-]+)/);if(match)token=match[1];else await wait(250)}
  if(!token)throw new Error(`Automation bridge unavailable\n${combined}`);
  let snapshot=await waitBody(token,'建立研究合同');
  if(snapshot.violations.length)throw new Error(`Unnamed controls: ${JSON.stringify(snapshot.violations)}`);
  await call(token,'/click',{text:'建立研究合同'});await waitBody(token,'项目名称');
  await call(token,'/fill',{label:'项目名称',value:'桌面 E2E 项目'});await call(token,'/fill',{label:'研究问题',value:'处理是否改变结果？'});await call(token,'/fill',{label:'纳入与排除标准',value:'数值观测'});
  await call(token,'/click',{text:'创建研究合同'});await waitBody(token,'智能工作流');
  await call(token,'/click',{text:'实验与复现'});await waitBody(token,'运行可复现实验');await call(token,'/click',{text:'运行可复现实验'});snapshot=await waitBody(token,'结果 SHA256',30000);
  if(!snapshot.body.includes('统计门禁')||snapshot.body.includes('统计门禁 未通过'))throw new Error(`Experiment statistics gate did not pass\n${snapshot.body}`);
  await call(token,'/click',{text:'设置与连接'});await waitBody(token,'Agent 任务');
  await call(token,'/key',{key:'TAB'});snapshot=(await call(token,'/snapshot')).value;if(!snapshot.active)throw new Error('Keyboard focus is not observable');
  const output={ok:true,title:snapshot.title,active:snapshot.active,experiment:true,agentPanel:true,buttonCount:snapshot.buttons.length,violations:snapshot.violations};
  fs.writeFileSync(path.join(root,'verification-logs','desktop-e2e.json'),JSON.stringify(output,null,2));
  await call(token,'/quit');await new Promise(resolve=>child.once('exit',resolve));console.log(JSON.stringify(output));
}
main().catch(error=>{console.error(error.stack||error);process.exit(1)});
