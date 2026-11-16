const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function setup() {
  const events = {}, focused = [], scroll = [], targets = new Map();
  const heading = { focus: options => focused.push(['heading', options]) };
  const section = { id: 'section-meds', querySelector: selector => selector === 'h2' ? heading : null };
  const document = {
    addEventListener: (name, fn) => { (events[name] ||= []).push(fn); },
    querySelector: selector => {
      const match = selector.match(/^\[data-field="(meds|other_meds)"\]\[data-row="(\d+)"\]\[data-col="(\d+)"\]$/);
      return match ? targets.get(`${match[1]}:${match[2]}:${match[3]}`) || null : null;
    },
    getElementById: id => id === section.id ? section : null,
  };
  const context = vm.createContext({ H: { ...H, autosaver: () => ({ changed() {} }) }, esc: H.esc, page: 'interview', document,
    window: { innerHeight: 600, scrollX: 0, scrollY: 200, scrollTo: (x,y) => scroll.push(['to',y]), scrollBy: (x,y) => scroll.push(['by',y]) } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({meds:[['A','Daily','', '', ''], ['B','Daily','','','']], other_meds:[['C','','',''],['D','','','']], details:{meds:[{},{}],other_meds:[{},{}]}}); renderInterview = () => {};`, context);
  function candidate(key, index, hidden = false, beforeTop = 100, afterTop = 140) {
    const checkbox = { focus: options => focused.push([`${key}:${index}:check`, options]), closest: () => renderedRow, getBoundingClientRect: () => ({ top: afterTop, bottom: afterTop + 50 }) };
    const renderedRow = { getBoundingClientRect: () => ({ top: afterTop, bottom: afterTop + 50 }), querySelector: selector => selector.includes('checked') ? checkbox : null };
    const target = { hidden, style: {}, scrollHeight: 20, focus: options => focused.push([`${key}:${index}:actual`, options]), closest: () => renderedRow, getBoundingClientRect: () => ({ top: afterTop, bottom: afterTop + 50 }) };
    targets.set(`${key}:${index}:${key === 'meds' ? 2 : 1}`, target);
    const oldInput = { dataset: { row: String(index) }, hidden, getBoundingClientRect: () => ({top: beforeTop, bottom: beforeTop + 50}) };
    const oldCheck = { getBoundingClientRect: () => ({top: beforeTop, bottom: beforeTop + 50}) };
    return { querySelector: selector => selector.includes('checked') ? oldCheck : oldInput, getBoundingClientRect: () => ({top: beforeTop, bottom: beforeTop + 50}) };
  }
  const row = { parentElement: null, closest: selector => selector === 'section' ? section : null };
  const dispatch = target => events.input.forEach(fn => fn({ target }));
  return { context, dispatch, row, focused, scroll, candidate, targets, section };
}

test('actual use filters the existing preset selector without replacing custom text', () => {
  const {context, dispatch} = setup();
  const select = { value: '', innerHTML: '' };
  const container = { querySelector: selector => selector === '[data-usage-preset]' ? select : null };
  const input = { dataset: { field: 'meds', row: '0', col: '2' }, tagName: 'INPUT', value: '1', closest: () => container };
  dispatch(input);
  assert.match(select.innerHTML, /7 matching presets/);
  assert.match(select.innerHTML, /1m — 1 in the morning/);
  assert.match(select.innerHTML, /1bd — 1 twice daily/);
  assert.doesNotMatch(select.innerHTML, /2bd —/);
  assert.equal((select.innerHTML.match(/<option /g) || []).length, 8);
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), '1');
  assert.equal(select.value, '');
  dispatch({ dataset: { usagePreset: 'meds', row: '0' }, value: '1m' });
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), '1 in the morning');
  input.value = '1 twice daily'; dispatch(input); assert.equal(select.value, '1bd');
  input.value = 'custom 1 tablet'; dispatch(input); assert.equal(select.value, '');
  assert.match(select.innerHTML, /Usage preset/); assert.match(select.innerHTML, /2bd —/);
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), 'custom 1 tablet');
  input.dataset = { field: 'other_meds', row: '0', col: '1' }; input.value = 'PRN'; dispatch(input);
  assert.equal(select.value, 'PRN'); assert.equal(vm.runInContext('interviewRecord.other_meds[0][1]', context), 'PRN');
  dispatch({ dataset: { usagePreset: 'other_meds', row: '0' }, value: '1m' });
  assert.equal(vm.runInContext('interviewRecord.other_meds[0][1]', context), '1 in the morning');
  const html = vm.runInContext('interviewOtherMedicineTable(interviewRecord.other_meds)', context);
  assert.match(html, /data-usage-preset="other_meds"/);
  assert.doesNotMatch(html, /data-usage-suggestions/);
});

test('checking, not using, and as instructed focus the next source medicine at its previous viewport position', async () => {
  const { context, dispatch, row, focused, scroll, candidate } = setup();
  row.nextElementSibling = candidate('meds', 1);
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].checked', context), true);
  assert.equal(focused.at(-1)[0], 'meds:1:actual'); assert.equal(focused.at(-1)[1].preventScroll, true);
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',40]]);
  dispatch({ dataset: { useField: 'use_status', useTable: 'meds', row: '0' }, value: 'not_using', closest: () => row });
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].use_status', context), 'not_using');
  assert.match(vm.runInContext('interviewMedicineTable(interviewRecord.meds, true)', context), /Reason<select/);
  assert.equal(focused.at(-1)[0], 'meds:1:actual');
  row.nextElementSibling = candidate('other_meds', 1);
  dispatch({ dataset: { otherChecked: '', row: '0' }, checked: true, closest: () => row });
  assert.equal(vm.runInContext('interviewRecord.details.other_meds[0].checked', context), true);
  assert.equal(focused.at(-1)[0], 'other_meds:1:actual');
  row.nextElementSibling = candidate('meds', 1);
  await vm.runInContext(`interviewClick({dataset:{interviewAsInstructed:'0'},closest: () => globalRow})`, Object.assign(context, {globalRow: row}));
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].checked', context), true);
  assert.equal(focused.at(-1)[0], 'meds:1:actual');
});

test('last row uses previous source row, and single row retains viewport at its section', () => {
  const {dispatch, row, focused, scroll, candidate} = setup();
  row.previousElementSibling = candidate('meds', 0, true);
  dispatch({ dataset: { medDetail: 'checked', row: '1' }, checked: false, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'meds:0:check');
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',40]]);
  row.previousElementSibling = null;
  dispatch({ dataset: { medDetail: 'checked', row: '1' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'heading');
  assert.equal(focused.at(-1)[1].preventScroll, true);
  assert.deepEqual(scroll.at(-1), ['to',200]);
});

test('navigation skips checked neighbours, falls back to earlier remaining row, and stops at section when complete', () => {
  const {context, dispatch, row, focused, candidate} = setup();
  vm.runInContext(`interviewRecord.meds.push(['C','Daily','','','']); interviewRecord.details.meds.push({checked: true, priority: 0});`, context);
  row.nextElementSibling = candidate('meds', 2);
  row.previousElementSibling = candidate('meds', 0);
  dispatch({ dataset: { medDetail: 'checked', row: '1' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'meds:0:actual');
  vm.runInContext('interviewRecord.details.meds[0].checked = true', context);
  dispatch({ dataset: { medDetail: 'checked', row: '1' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'heading');
  assert.equal(focused.at(-1)[1].preventScroll, true);
});

test('an offscreen next medicine is brought to the nearest viewport edge', () => {
  const {dispatch, row, focused, scroll, candidate} = setup();
  row.nextElementSibling = candidate('meds', 1, false, 650, 590);
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'meds:1:actual');
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',40]]);
});

test('not using a found medicine advances within found medicines without checking or moving it', () => {
  const {context, dispatch, row, focused, candidate} = setup();
  row.nextElementSibling = candidate('other_meds', 1);
  const beforeChecked = vm.runInContext('interviewRecord.details.other_meds[0].checked', context);
  dispatch({ dataset: { useField: 'use_status', useTable: 'other_meds', row: '0' }, value: 'not_using', closest: () => row });
  assert.equal(focused.at(-1)[0], 'other_meds:1:actual');
  assert.equal(vm.runInContext('interviewRecord.details.other_meds[0].use_status', context), 'not_using');
  assert.equal(vm.runInContext('interviewRecord.details.other_meds[0].checked', context), beforeChecked);
  const order = vm.runInContext('interviewOtherMedicineTable(interviewRecord.other_meds)', context);
  assert(order.indexOf('>D</textarea>') < order.indexOf('>C</textarea>'));
  assert.match(vm.runInContext('interviewOtherMedicineTable(interviewRecord.other_meds)', context), /Reason<select/);
});

test('an offscreen next row scrolls its containing scroller to the nearest edge', () => {
  const {context, dispatch, row, focused, candidate} = setup();
  context.getComputedStyle = () => ({overflowY: 'auto'});
  const scroller = { parentElement: null, scrollHeight: 1000, clientHeight: 300, scrollTop: 100, isConnected: true, getBoundingClientRect: () => ({top: 50, bottom: 350}) };
  row.parentElement = scroller;
  row.nextElementSibling = candidate('meds', 1, false, 400, 330);
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'meds:1:actual');
  assert.equal(scroller.scrollTop, 130);
});

test('a tall row preserves the visible actual-use control anchor', () => {
  const {dispatch, row, focused, scroll, candidate} = setup();
  const next = candidate('meds', 1, false, 120, 160);
  next.getBoundingClientRect = () => ({top: 100, bottom: 1000});
  row.nextElementSibling = next;
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: true, type: 'checkbox', closest: () => row });
  assert.equal(focused.at(-1)[0], 'meds:1:actual');
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',40]]);
});

test('found-medicine navigation skips other entries already marked not using', () => {
  const {context, dispatch, row, focused, candidate} = setup();
  vm.runInContext(`interviewRecord.other_meds.push(['E','','','']); interviewRecord.details.other_meds[1].use_status = 'not_using'; interviewRecord.details.other_meds.push({checked: false, priority: 0});`, context);
  const skipped = candidate('other_meds', 1), next = candidate('other_meds', 2);
  skipped.nextElementSibling = next; row.nextElementSibling = skipped;
  dispatch({ dataset: { useField: 'use_status', useTable: 'other_meds', row: '0' }, value: 'not_using', closest: () => row });
  assert.equal(focused.at(-1)[0], 'other_meds:2:actual');
});

test('focus clears a stuck header and context, without treating a flowing context as pinned', () => {
  const {context, dispatch, row, scroll, candidate} = setup();
  const header = { position: 'sticky', top: '0px', getBoundingClientRect: () => ({top: 0, bottom: 96}) };
  const panel = { position: 'sticky', top: '96px', getBoundingClientRect: () => ({top: 96, bottom: 150}) };
  const main = { getBoundingClientRect: () => ({top: 0}) };
  const originalQuery = context.document.querySelector;
  context.document.querySelector = selector => selector === 'main' ? main : originalQuery(selector);
  context.document.querySelectorAll = () => [header, panel];
  context.getComputedStyle = node => ({position: node.position, top: node.top});
  row.nextElementSibling = candidate('meds', 1, false, 120, 80);
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: true, type: 'checkbox', closest: () => row });
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',-70]]);
  panel.getBoundingClientRect = () => ({top: 220, bottom: 274});
  row.nextElementSibling = candidate('meds', 1, false, 120, 160);
  dispatch({ dataset: { medDetail: 'checked', row: '0' }, checked: false, type: 'checkbox', closest: () => row });
  assert.deepEqual(scroll.slice(-2), [['to',200], ['by',40]]);
});
