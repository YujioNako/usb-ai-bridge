import assert from 'node:assert/strict';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {WindowsTools} from './client.mjs';import {createPanel} from './serial-panel.mjs';import './attachments.mjs';import './clipboard-files.mjs';
const here=path.dirname(fileURLToPath(import.meta.url)),tools=await new WindowsTools(path.join(here,'self-test','fixtures')).init();
try{
 for(const name of ['sample.xlsx','sample.xls']){const r=await tools.files({op:'read',path:name});assert.equal(r.rows[3].cells[1].value,350);assert(r.sheets.includes('收支'))}
 assert.match((await tools.files({op:'read',path:'report.docx'})).content,/预算 1250/);
 const pdf=await tools.files({op:'read',path:'report.pdf',limit:1});assert.equal(pdf.total_pages,2);assert.match(pdf.pages[0].text,/budget 1250/);
 const zip=await tools.files({op:'read',path:'bundle.zip'});assert.equal(zip.total_entries,2);assert.match((await tools.files({op:'read',path:'bundle.zip',find:'资料/hello.txt'})).content,/数量 3/);
 const server=createPanel({ready:false},'self-test-only');await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{const base='http://127.0.0.1:'+server.address().port;const html=await(await fetch(base)).text();for(const id of ['regenerate-dialog','usage-prices-dialog','session-model-dialog'])assert(html.includes(id));const script=await(await fetch(base+'/workbench.js')).text();for(const name of ['openRegeneration','usage_display','WorkbenchSync'])assert(script.includes(name));assert.equal((await(await fetch(base+'/health')).json()).transport,'serial')}
 finally{await new Promise(r=>server.close(r))}
 console.log('PASS: packaged Node '+process.version+', modules, XLS/XLSX, DOCX, PDF, ZIP and latest local console. No Pi connection or AI call was made.');
}finally{await tools.close()}
