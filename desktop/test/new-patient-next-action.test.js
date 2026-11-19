const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../renderer/helpers');

// The engine now gives a new patient the next step "offer a time". This is the renderer side of that contract:
// pure action mapping and source-level wiring only. It never calls the engine and sends nothing.
// The primary-action logic lives inside showPatient (not exported), so this checks the wiring, not a rendered pane.
test('a new patient (intake stage) offers the offer action, so "offer a time" can become the primary action', () => {
  assert.ok(H.stageActions({ stage: 'intake', folder: '' }).includes('offer'));
});

test('the label "offer a time" is aliased to the offer action in the patient pane', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/patients.js'), 'utf8');
  assert.match(source, /'offer a time': 'offer'/);
});

test('the retired review-intake label is not aliased to any action, so it would never have been a working primary action', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/patients.js'), 'utf8');
  assert.doesNotMatch(source, /'review intake':/);
});

test('the primary action is only used when it is among the stage actions, so offer stays an explicit pharmacist action', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/patients.js'), 'utf8');
  assert.match(source, /!shownActions\.includes\(primaryAction\)/);
  // Choosing the action only opens the form; sending is a separate explicit step (data-message-send / offer send button).
  assert.match(source, /if \(action && \(availableActions\(p, milestones\)\.includes\(action\)/);
});
