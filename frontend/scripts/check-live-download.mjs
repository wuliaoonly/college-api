import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve('..'),origin='https://101.37.242.39';
const credentials=await readFile(path.join(root,'.tools/private/部署管理员账号.txt'),'utf8');
const username=credentials.match(/^Username\s*[:=]\s*(.+)$/mi)?.[1]?.trim();
const password=credentials.match(/^Password\s*[:=]\s*(.+)$/mi)?.[1]?.trim();
assert(username&&password,'Private deployment credentials unavailable');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:1020},acceptDownloads:true});
let csrf='';
let page;
try {
  const login=await context.request.post(origin+'/portal-api/auth/login',{data:{username,password}});
  assert(login.ok(),'Production administrator login failed');csrf=(await login.json()).csrf;
  page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin+'/download');
  await page.getByRole('heading',{name:'选择你的 AI 编程工具',exact:true}).waitFor();
  const claude=page.getByLabel('Claude Code',{exact:false}),harness=page.getByLabel('DeepSeek Harness',{exact:false});
  const button=page.getByRole('button',{name:'下载我的 Windows 安装助手',exact:true});
  assert(await button.isEnabled(),'Administrator software-only download still disabled');
  for(const choice of ['claude','harness','both']) {
    await claude.setChecked(choice!=='harness');await harness.setChecked(choice!=='claude');
    const pending=page.waitForEvent('download');await button.click();
    const download=await pending;
    await download.saveAs(path.join(root,'artifacts/live-keyless-'+choice+'.zip'));
    assert.equal(await download.failure(),null,'Production ZIP download failed');
    await page.getByRole('alert').getByText('下载已开始，可先安装软件；分配 Key 后重新下载完成模型配置',{exact:true}).waitFor();
  }
  await page.screenshot({path:path.join(root,'artifacts/website-live-client-options.png'),fullPage:true});
  await claude.uncheck();await harness.uncheck();assert(await button.isDisabled(),'Empty selection should be disabled');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile download page overflows');
  assert.deepEqual(errors,[]);
  console.log('PASS: trusted public HTTPS, keyless administrator browser downloads for all three selections, empty selection, and mobile layout.');
} catch(error) {
  if(page) {
    await page.screenshot({path:path.join(root,'artifacts/website-live-download-debug.png'),fullPage:true});
    console.log('Download verification screen:',(await page.locator('body').innerText()).slice(0,1600));
  }
  throw error;
} finally {
  if(csrf) await context.request.post(origin+'/portal-api/auth/logout',{headers:{'X-CSRF-Token':csrf}});
  await browser.close();
}
