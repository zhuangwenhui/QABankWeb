/**
 * utils.js:orderedKeys 的行为测试。
 *
 * 这个函数是「学科分布在两个页面显示成两种顺序」的修法:后端给不了顺序
 * (Flask 的 json.sort_keys 默认 true,序列化时按码点重排 key),所以定序放在前端,
 * 且必须**只有一份实现** —— 题目管理页与错题本页共用它。
 *
 * 跑法:node --test tests/js/
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadGlobalScript } = require('./load');

const { orderedKeys } = loadGlobalScript('utils.js', ['orderedKeys', 'pageNumbers']);

/**
 * 跨 realm 修正:脚本跑在 vm 沙箱里,它造的数组来自另一个 realm、原型不同,
 * deepStrictEqual 会以「结构相同但引用不等」失败。取回本 realm 再比。
 */
function ordered(data, preset) {
  return Array.from(orderedKeys(data, preset));
}

// 与 config.SUBJECTS 一致(测试里写死:这就是要钉住的那个顺序)
const SUBJECTS = ['算法', '向量解析', '复变函数', '微分方程', '微积分', '概率统计', '线性代数'];

test('按预设顺序排,而不是按对象本身的键序', () => {
  // 模拟接口返回:Flask 已按码点重排过,算法被挤到了后面
  const fromApi = { 向量解析: 3, 微积分: 5, 算法: 9, 线性代数: 1 };
  assert.deepStrictEqual(
    ordered(fromApi, SUBJECTS),
    ['算法', '向量解析', '微积分', '线性代数'],
    '算法应排在最前(config.SUBJECTS 里它是第一个)');
});

test('预设里没有的键追加在后面,并保持原有相对顺序', () => {
  const data = { 天文学: 1, 微积分: 2, 地质学: 3, 算法: 4 };
  assert.deepStrictEqual(
    ordered(data, SUBJECTS),
    ['算法', '微积分', '天文学', '地质学'],
    '枚举外的科目要保留,且按它们在对象里的先后追加');
});

test('预设里有、数据里没有的键不出现', () => {
  assert.deepStrictEqual(ordered({ 微积分: 1 }, SUBJECTS), ['微积分']);
});

test('空数据与空预设都不炸', () => {
  assert.deepStrictEqual(ordered({}, SUBJECTS), []);
  assert.deepStrictEqual(ordered(null, SUBJECTS), []);
  assert.deepStrictEqual(ordered({ b: 1, a: 2 }, null), ['b', 'a']);
  assert.deepStrictEqual(ordered({ b: 1, a: 2 }, []), ['b', 'a']);
});

test('不丢键、不重复键', () => {
  const data = { 微积分: 1, 天文学: 2, 算法: 3, 复变函数: 4 };
  const out = ordered(data, SUBJECTS);
  assert.strictEqual(out.length, Object.keys(data).length, '键数变了');
  assert.strictEqual(new Set(out).size, out.length, '出现了重复键');
  for (const k of Object.keys(data)) {
    assert.ok(out.indexOf(k) !== -1, `丢了键 ${k}`);
  }
});

test('预设里出现重复项时不产生重复输出', () => {
  const out = ordered({ 算法: 1 }, ['算法', '算法', '微积分']);
  assert.deepStrictEqual(out, ['算法']);
});

test('原型链上的属性不算数据自己的键', () => {
  // 用 in 判断会把 toString 这类算进来;这里确认实现没有那个毛病
  const out = ordered({ 算法: 1 }, ['toString', 'hasOwnProperty', '算法']);
  assert.deepStrictEqual(out, ['算法'],
    '预设里写了原型链上的名字时,不该凭空多出键来');
});
