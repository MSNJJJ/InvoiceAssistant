// verify_lib.mjs — 公共库 lib.js 纯函数自检（不依赖 dev-browser 全局）
//
// 用 new Function 提取 lib.js 的纯函数引用并验证行为，确保抽库后逻辑不变。
// 运行：node tools/verify_lib.mjs

import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const libPath = join(__dirname, '..', 'skills', '_common', 'lib.js');
const code = fs.readFileSync(libPath, 'utf8');

// lib.js 无模块导出（QuickJS 风格），用 new Function 暴露内部函数引用
const factory = new Function(code + '\nreturn { ts, fmtLog, step, waitForAppReady, waitForSheetReady };');
const lib = factory();

let ok = true;
function check(name, cond) {
  if (!cond) { ok = false; console.error('  FAIL:', name); }
  else console.log('  pass:', name);
}

console.log('验证 lib.js 纯函数：');

// ts 格式 YYYY-MM-DD HH:MM:SS
const t = lib.ts();
check('ts() 返回 "YYYY-MM-DD HH:MM:SS" 格式', /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(t));

// fmtLog 含 tag / stage / extra
const l = lib.fmtLog('CREATE', 'INPUT', 'hello', { a: 1 });
check('fmtLog 含 tag [CREATE]', l.includes('[CREATE]'));
check('fmtLog 含 stage INPUT', l.includes('INPUT'));
check('fmtLog 含 extra JSON', l.includes('"a":1'));

// step 输出格式 [步骤 n/N] 描述
const logs = [];
const orig = console.log;
console.log = (...a) => logs.push(a.join(' '));
lib.step(2, 5, '打开文档');
console.log = orig;
check('step 输出 "[步骤 2/5] 打开文档"', logs[0] === '[步骤 2/5] 打开文档');

// 等待函数存在且为 async function
check('waitForAppReady 是函数', typeof lib.waitForAppReady === 'function');
check('waitForSheetReady 是函数', typeof lib.waitForSheetReady === 'function');

if (ok) {
  console.log('\n✅ lib.js 纯函数验证通过');
} else {
  console.error('\n❌ lib.js 验证失败');
  process.exit(1);
}
