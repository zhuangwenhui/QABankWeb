/**
 * 把 static/js/ 里的浏览器脚本加载进 node,供行为测试调用。
 *
 * 这些脚本是 IIFE + window.XXX 导出、没有模块系统(前端刻意零构建)。所以这里造一个
 * 最小沙箱:给一个空 window,用 vm 跑源码,再把挂上去的东西取回来。
 *
 * 不用 require:文件不是 CommonJS 模块。也不切片源码文本 —— 那样测的是切片,
 * 不是真正会上线的整份文件。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');

/** 最小 DOM 桩:只够脚本加载不炸。真需要 DOM 的功能不在这里测(那是 e2e 的活)。 */
function makeSandbox() {
  const noop = () => {};
  const el = () => ({
    classList: { add: noop, remove: noop, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    appendChild: noop,
    setAttribute: noop,
    innerHTML: '',
    textContent: '',
  });
  const win = {};
  const sandbox = {
    window: win,
    document: {
      createElement: el,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    console,
    setTimeout,
    clearTimeout,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  return sandbox;
}

/**
 * 加载一个 static/js 下的脚本,返回它挂到 window 上的导出对象。
 * @param {string} file 相对 static/js/ 的文件名,如 'qd_render.js'
 * @param {string} exportName window 上的导出名,如 'QDRender'
 */
function loadBrowserScript(file, exportName) {
  const src = fs.readFileSync(path.join(ROOT, 'static', 'js', file), 'utf8');
  const sandbox = makeSandbox();
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: file });
  const api = sandbox.window[exportName];
  if (!api) {
    throw new Error(`${file} 没有把 ${exportName} 挂到 window 上(导出名改了?)`);
  }
  return api;
}

/**
 * 加载 utils.js 这类**不走 window 导出**的脚本:它用顶层函数声明,函数直接落在全局上。
 * 返回沙箱本身,调用方按名字取。
 * @param {string} file 相对 static/js/ 的文件名
 * @param {string[]} names 期望存在的函数名;缺任何一个就报错(改名要立刻发现)
 */
function loadGlobalScript(file, names) {
  const src = fs.readFileSync(path.join(ROOT, 'static', 'js', file), 'utf8');
  const sandbox = makeSandbox();
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: file });
  for (const n of names) {
    if (typeof sandbox[n] !== 'function') {
      throw new Error(`${file} 里没有全局函数 ${n}(改名或改成了局部?)`);
    }
  }
  return sandbox;
}

module.exports = { loadBrowserScript, loadGlobalScript, ROOT };
