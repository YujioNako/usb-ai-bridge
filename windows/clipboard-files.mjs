import {execFile} from 'node:child_process';
// Read file-drop data only, and only in response to the user's paste action.
// Plain text, passwords and clipboard history are never queried.
export async function readClipboardFiles(){
 if(process.platform!=='win32')throw Error('此粘贴入口需要 Windows 客户端');
 const script="$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Add-Type -AssemblyName System.Windows.Forms; $items=@([Windows.Forms.Clipboard]::GetFileDropList()); if($items.Count -gt 20){throw '一次最多粘贴 20 个文件'}; ConvertTo-Json -Compress -InputObject $items";
 return new Promise((resolve,reject)=>execFile('powershell.exe',['-NoProfile','-NonInteractive','-STA','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],{windowsHide:true,timeout:12000,maxBuffer:65536,encoding:'utf8'},(error,stdout)=>{
  if(error)return reject(Error('无法读取文件剪贴板，请重新复制文件后重试，或使用选择文件'));
  try{const items=JSON.parse(stdout.trim());if(!Array.isArray(items)||items.length>20||items.some(x=>typeof x!=='string'))throw Error();resolve(items)}catch{reject(Error('文件剪贴板格式无效'))}
 }));
}
