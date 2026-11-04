// 单元测试：插件「精确选图」文件名匹配纯函数（从 extension/injects/ui.js 中 <fc-asset-name-match> 标记段抽取）
// 运行：node tests/test_asset_name_match.js
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const src = fs.readFileSync(path.join(__dirname, "..", "extension", "injects", "ui.js"), "utf8");
const m = src.match(/\/\/ <fc-asset-name-match>[^\n]*\n([\s\S]*?)\/\/ <\/fc-asset-name-match>/);
assert.ok(m, "未在 ui.js 中找到 <fc-asset-name-match> 标记段");
const api = new Function(`${m[1]}
return { normalizeAssetName, isExactAssetNameMatch, looksLikeAssetFileName, buildAssetSearchQueries, pickExactAssetCandidate };`)();
const { normalizeAssetName, isExactAssetNameMatch, looksLikeAssetFileName, buildAssetSearchQueries, pickExactAssetCandidate } = api;

let passed = 0;
function t(name, fn) { fn(); passed++; console.log("ok -", name); }

t("normalize: case / whitespace / full-width / zero-width", () => {
  assert.strictEqual(normalizeAssetName("  FC0001.JPG "), "fc0001.jpg");
  assert.strictEqual(normalizeAssetName("ＦＣ０００１．ｊｐｇ"), "fc0001.jpg");
  assert.strictEqual(normalizeAssetName("1.jpg\u200b"), "1.jpg");
  assert.strictEqual(normalizeAssetName("a   b.png"), "a b.png");
  assert.strictEqual(normalizeAssetName(null), "");
});

t("exact: identical names match", () => {
  assert.ok(isExactAssetNameMatch("1.jpg", "1.jpg"));
  assert.ok(isExactAssetNameMatch("FC0001.jpg", " fc0001.JPG "));
  assert.ok(isExactAssetNameMatch("FC0001.jpg", "FC0001.jpeg"), "jpg ≡ jpeg");
});

t("exact: no substring / prefix collisions (old numeric names)", () => {
  for (const other of ["21.jpg", "11.jpg", "10.jpg", "12.jpg", "100.jpg", "01.jpg", "1 (1).jpg", "FC0001.jpg"]) {
    assert.ok(!isExactAssetNameMatch("1.jpg", other), `1.jpg must not match ${other}`);
  }
  assert.ok(!isExactAssetNameMatch("FC0001.jpg", "FC00010.jpg"));
  assert.ok(!isExactAssetNameMatch("FC0001.jpg", "FC0011.jpg"));
  assert.ok(!isExactAssetNameMatch("FC0001.jpg", "FC0001.png"), "different real extensions are different files");
});

t("exact: page without extension only accepted for distinctive stems", () => {
  assert.ok(isExactAssetNameMatch("FC0001.jpg", "FC0001"));
  assert.ok(!isExactAssetNameMatch("1.jpg", "1"), "plain counter text '1' must not match 1.jpg");
  assert.ok(!isExactAssetNameMatch("12.jpg", "12"));
  assert.ok(!isExactAssetNameMatch("", "1.jpg"));
  assert.ok(!isExactAssetNameMatch("1.jpg", ""));
});

t("looksLikeAssetFileName", () => {
  assert.ok(looksLikeAssetFileName("24.jpg"));
  assert.ok(looksLikeAssetFileName("FC0001.PNG"));
  assert.ok(!looksLikeAssetFileName("添加到提示"));
  assert.ok(!looksLikeAssetFileName("最近"));
});

t("buildAssetSearchQueries: full name then stem", () => {
  assert.deepStrictEqual(buildAssetSearchQueries("FC0001.jpg"), ["FC0001.jpg", "FC0001"]);
  assert.deepStrictEqual(buildAssetSearchQueries("noext"), ["noext"]);
  assert.deepStrictEqual(buildAssetSearchQueries(""), []);
});

t("pickExactAssetCandidate: list from screenshot, first exact match wins (most recent)", () => {
  const list = ["1.jpg", "4.jpg", "2.jpg", "3.jpg", "5.jpg", "24.jpg", "17.jpg", "19.jpg", "21.jpg", "22.jpg", "1.jpg"]
    .map((n, i) => ({ name: n, i }));
  assert.strictEqual(pickExactAssetCandidate(list, "1.jpg").i, 0);
  assert.strictEqual(pickExactAssetCandidate(list, "21.jpg").i, 8);
  assert.strictEqual(pickExactAssetCandidate(list, "2.jpg").i, 2);
  assert.strictEqual(pickExactAssetCandidate(list, "11.jpg"), null);
  // 多个名称来源（文本 / aria-label / alt）
  const multi = [{ names: ["more_vert", "21.jpg"], i: 0 }, { names: ["图片", "1.jpg"], i: 1 }];
  assert.strictEqual(pickExactAssetCandidate(multi, "1.jpg").i, 1);
  // 容器的完整文本是多个文件名拼接时绝不命中
  assert.strictEqual(pickExactAssetCandidate([{ names: ["1.jpg4.jpg2.jpg"] }], "1.jpg"), null);
  assert.strictEqual(pickExactAssetCandidate([{ names: ["1.jpg 4.jpg 2.jpg"] }], "1.jpg"), null);
});

console.log(`\nAll ${passed} test groups passed.`);
