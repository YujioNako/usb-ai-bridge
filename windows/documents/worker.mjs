import fs from 'node:fs/promises';
import path from 'node:path';
import {crc32} from 'node:zlib';
import yauzl from 'yauzl';
import * as XLSX from 'xlsx';
import WordExtractor from 'word-extractor';
const MAX_FILE=100000000,MAX_ENTRY=32000000,MAX_UNPACKED=100000000;
console.log=(...args)=>console.error(...args);
const bounded=(n,d,max)=>Number.isInteger(n)&&n>=0?Math.min(n,max):d;
function safeName(n){
 if(typeof n!=='string'||n.includes('\\')||n.startsWith('/')||n.includes('\0'))return false;
 return n.split('/').filter(Boolean).every(p=>p!=='.'&&p!=='..'&&!/[<>:"|?*\x00-\x1f]/.test(p)&&!/[. ]$/.test(p)&&!/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(p));
}
async function zipIndex(input){
 const z=await new Promise((resolve,reject)=>{const opts={lazyEntries:true,autoClose:false,validateEntrySizes:true,strictFileNames:true};const cb=(e,z)=>e?reject(e):resolve(z);Buffer.isBuffer(input)?yauzl.fromBuffer(input,opts,cb):yauzl.open(input,opts,cb)});
 try{
  const entries=[];let total=0;const names=new Set();
  await new Promise((resolve,reject)=>{z.on('error',reject);z.on('entry',e=>{
   try{
    if(entries.length>=10000||!safeName(e.fileName))throw Error('压缩包目录过多或包含不安全路径');
    const mode=(e.externalFileAttributes>>>16)&0xf000;
    if(mode&&mode!==0x8000&&mode!==0x4000)throw Error('压缩包包含链接或特殊文件，不能处理');
    if(e.generalPurposeBitFlag&1)throw Error('暂不支持加密压缩包，请先自行解密');
    const key=e.fileName.replace(/\/$/,'').toLowerCase();if(names.has(key))throw Error('压缩包存在重复或大小写冲突路径');names.add(key);
    total+=e.uncompressedSize;if(total>MAX_UNPACKED||e.uncompressedSize>MAX_ENTRY)throw Error('压缩包展开体积超限（合计 100 MB，单项 32 MB）');
    entries.push(e);z.readEntry();
   }catch(e){reject(e)}
  });z.on('end',resolve);z.readEntry()});
  return {z,entries,total};
 }catch(e){z.close();throw e;}
}
async function zipBytes(index,entry){
 const stream=await new Promise((resolve,reject)=>index.z.openReadStream(entry,(e,s)=>e?reject(e):resolve(s)));
 const chunks=[];let bytes=0;
 for await(const b of stream){bytes+=b.length;if(bytes>MAX_ENTRY||bytes>entry.uncompressedSize){stream.destroy();throw Error('压缩项实际体积超限')}chunks.push(b)}
 if(bytes!==entry.uncompressedSize)throw Error('压缩项长度不一致');
 const result=Buffer.concat(chunks);if(crc32(result)!==entry.crc32)throw Error('压缩项 CRC 校验不一致');return result;
}
function textResult(text,a,extra={}){const offset=bounded(a.offset,0,text.length),limit=Math.max(1,bounded(a.limit,24000,48000));return {...extra,offset,next_offset:offset+Math.min(limit,Math.max(0,text.length-offset)),total_characters:text.length,content:text.slice(offset,offset+limit),truncated:offset+limit<text.length};}
async function parse(input,filename,a){
 const ext=path.extname(filename).toLowerCase();let index;
 if(a.op?.startsWith('archive_')&&ext!=='.zip')throw Error('压缩包操作目前仅支持 ZIP');
 try{
  if(['.zip','.xlsx','.xlsm','.xlsb','.ods','.docx'].includes(ext))index=await zipIndex(input);
  if(ext==='.zip'){
   const entryName=a.entry||a.find;
   if(a.op==='archive_extract'){
    if(Buffer.isBuffer(input)||!a.destination)throw Error('需要本地压缩包和未存在的目标目录');
    let selected=index.entries;if(entryName){selected=selected.filter(e=>e.fileName===entryName);if(!selected.length)throw Error('压缩包内没有指定文件');}
    // Preflight every path before creating anything; never merge into an existing directory.
    for(const e of selected){const target=path.resolve(a.destination,e.fileName);if(!target.startsWith(path.resolve(a.destination)+path.sep))throw Error('解压路径越界');}
    await fs.mkdir(a.destination,{recursive:false});let count=0;
    try{for(const e of selected){const target=path.join(a.destination,e.fileName);if(e.fileName.endsWith('/')){await fs.mkdir(target,{recursive:true});continue;}await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,await zipBytes(index,e),{flag:'wx'});count++;}}catch(e){throw Error('解压未完成，已写入的文件保留在新目录中：'+e.message)}
    return {format:'zip',extracted_files:count,uncompressed_bytes:index.total};
   }
   if(entryName){const e=index.entries.find(e=>e.fileName===entryName&&!e.fileName.endsWith('/'));if(!e)throw Error('压缩包内没有指定文件');if(/\.zip$/i.test(entryName))throw Error('嵌套压缩包请先解压后单独读取');return {...await parse(await zipBytes(index,e),entryName,{...a,op:'document',find:undefined,entry:undefined}),archive_entry:entryName};}
   const offset=bounded(a.offset,0,index.entries.length),limit=Math.max(1,bounded(a.limit,100,200));
   return {format:'zip',entries:index.entries.slice(offset,offset+limit).map(e=>({name:e.fileName,bytes:e.uncompressedSize,directory:e.fileName.endsWith('/')})),total_entries:index.entries.length,uncompressed_bytes:index.total,next_offset:Math.min(index.entries.length,offset+limit),truncated:offset+limit<index.entries.length,hint:'files.read 的 find 可填写一个成员的完整名称直接读取；archive_extract 可解压到全新目录，不会执行其中程序。'};
  }
  const data=Buffer.isBuffer(input)?input:await fs.readFile(input);
  if(['.xlsx','.xls','.xlsm','.xlsb','.ods','.csv','.tsv'].includes(ext)){
   const offset=bounded(a.offset,0,1000000),limit=Math.max(1,bounded(a.limit,100,200));
   const book=XLSX.read(data,{type:'buffer',cellFormula:true,cellDates:false,cellNF:true,bookVBA:false,sheetRows:offset+limit+1,codepage:65001});
   const selected=a.sheet||a.find||book.SheetNames[0];if(!book.SheetNames.includes(selected))throw Error('工作表不存在：'+selected);
   const sheet=book.Sheets[selected];const range=XLSX.utils.decode_range(sheet['!fullref']||sheet['!ref']||'A1');
   const column=bounded(a.column,0,16383),columns=Math.max(1,bounded(a.columns,32,64)),rows=[];
   for(let r=offset;r<=range.e.r&&r<offset+limit;r++){
    const cells=[];for(let c=column;c<=range.e.c&&c<column+columns;c++){const address=XLSX.utils.encode_cell({r,c}),cell=sheet[address];if(cell)cells.push({cell:address,value:typeof cell.v==='string'?cell.v.slice(0,2000):cell.v,...(cell.w!==undefined?{display:String(cell.w).slice(0,2000)}:{}),...(cell.z?{number_format:cell.z}:{}),...(typeof cell.v==='string'&&cell.v.length>2000?{cell_text_truncated:true}:{}),...(cell.f?{formula:cell.f}: {})});}
    rows.push({row:r+1,cells});if(JSON.stringify(rows).length>44000){rows.pop();break;}
   }
   return {format:'spreadsheet',sheet:selected,sheets:book.SheetNames,range:XLSX.utils.encode_range(range),rows,next_offset:offset+rows.length,truncated:offset+rows.length<=range.e.r,column,next_column:Math.min(range.e.c+1,column+columns),columns_truncated:column+columns<=range.e.c,note:'数值来自文件内的缓存值；不运行宏、不刷新外部连接、不重算公式。offset 为零起始行号，find/sheet 可指定工作表。'};
  }
  if(ext==='.doc'||ext==='.docx'){
   const doc=await new WordExtractor().extract(data);
   const text=[doc.getBody(),doc.getHeaders(),doc.getFootnotes(),doc.getEndnotes(),doc.getAnnotations(),doc.getTextboxes()].filter(Boolean).join('\n\n');
   return textResult(text,a,{format:ext.slice(1),note:'提取正文、表格文本、页眉页脚和批注；不保留页面版式，不解析嵌入图片，不执行宏。'});
  }
  if(ext==='.pdf'){
   const {default:DOMMatrix}=await import('@thednp/dommatrix');globalThis.DOMMatrix=DOMMatrix;
   const pdfjs=await import('pdfjs-dist/legacy/build/pdf.mjs');
   const base=new URL('./node_modules/pdfjs-dist/',import.meta.url);
   const task=pdfjs.getDocument({data:new Uint8Array(data),isEvalSupported:false,disableFontFace:true,useSystemFonts:false,useWasm:false,cMapUrl:new URL('cmaps/',base).href,cMapPacked:true,standardFontDataUrl:new URL('standard_fonts/',base).href,verbosity:0});
   const pdf=await task.promise;
   try{const offset=bounded(a.offset,0,pdf.numPages),limit=Math.max(1,bounded(a.limit,3,5)),pages=[];
    for(let n=offset;n<Math.min(pdf.numPages,offset+limit);n++){const p=await pdf.getPage(n+1);const content=await p.getTextContent();const text=content.items.map(x=>x.str+(x.hasEOL?'\n':' ')).join('');pages.push({page:n+1,text:text.slice(0,12000),truncated:text.length>12000});p.cleanup();}
    return {format:'pdf',total_pages:pdf.numPages,pages,next_offset:offset+pages.length,truncated:offset+pages.length<pdf.numPages,note:pages.every(p=>!p.text.trim())?'这些页面没有可提取文本，可能需要 OCR；当前未执行 OCR。':'offset 为零起始页号；文本不代表原始页面版式。'};
   }finally{await task.destroy()}
  }
  if(/\.(7z|rar|gz|tar|bz2|xz)$/i.test(filename))throw Error('已保存原文件；目前内置解析 ZIP，其他压缩格式请先转换成 ZIP 或通过已授权的终端工具处理');
  if(data.includes(0))throw Error('暂不支持直接解析此二进制格式；文件已保留，可通过其他工具处理');
  let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(data)}catch{try{text=new TextDecoder('gb18030',{fatal:true}).decode(data)}catch{throw Error('文本编码无法识别，请转换为 UTF-8')}}
  return textResult(text,a,{format:'text'});
 }finally{index?.z.close()}
}
try{
 let raw='';for await(const b of process.stdin){raw+=b;if(raw.length>20000)throw Error('参数过大')}
 const a=JSON.parse(raw);const stat=await fs.stat(a.path);if(!stat.isFile()||stat.size>MAX_FILE)throw Error('文件不是普通文件或超过 100 MB');
 const result=await parse(a.path,a.path,a);const output=JSON.stringify(result);if(Buffer.byteLength(output)>250000)throw Error('输出过大，请缩小读取范围');process.stdout.write(output);
}catch(e){process.stdout.write(JSON.stringify({error:String(e.message).slice(0,1200)}));process.exitCode=1}
