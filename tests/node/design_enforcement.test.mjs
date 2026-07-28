import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseIssueNumbers,
  hasValidOptIn,
  chooseState,
  canonicalLabels,
  targetNumbers,
  desiredState,
  buildAnnouncement,
  CORRECTIVE_MARKER,
  ANNOUNCEMENT_MARKER,
} from '../../.github/actions/design-enforcement/index.js';

test('parses closing references from a pull request body', () => {
  assert.deepEqual(parseIssueNumbers('Fixes #12 and closes https://github.com/org/repo/issues/34'), [12, 34]);
});

test('requires a checked clanker opt-in and every required field', () => {
  const body = '- [x] Request Clanker queue\n\n### What happened?\nSomething broke\n\n### Affected area\nCI';
  assert.equal(hasValidOptIn(body, [['What happened?'], ['Affected area']]), true);
  assert.equal(hasValidOptIn(body.replace('[x]', '[ ]'), [['What happened?'], ['Affected area']]), false);
  assert.equal(hasValidOptIn(body.replace('Something broke', ''), [['What happened?'], ['Affected area']]), false);
});

test('repairs invalid workflow label combinations to discussion', () => {
  assert.equal(chooseState(['1-triage', '2-discussing']), '2-discussing');
  assert.equal(chooseState(['3-human-queue', '3-clanker-queue']), '2-discussing');
  assert.equal(chooseState([]), '2-discussing');
  assert.equal(chooseState(['4-review']), '4-review');
});

test('announcement starts with required text and has one hidden marker', () => {
  const body = buildAnnouncement('https://example.test/hive', 42);
  assert.equal(body.startsWith('This issue is now in the `clanker-queue` and will be doled out to the community army. Check https://example.test/hive to find out more. Good Hunting.'), true);
  assert.equal(body.match(new RegExp(ANNOUNCEMENT_MARKER, 'g')).length, 1);
  assert.match(body, /Next action:.*#42/);
});

test('corrective marker is distinct from announcement marker', () => {
  assert.notEqual(CORRECTIVE_MARKER, ANNOUNCEMENT_MARKER);
});


test('canonical labels remove all metadata and retain only state overlays', () => {
  assert.deepEqual(canonicalLabels(['kind/bug', '1-triage', 'blocked', 'hold']), ['1-triage', 'blocked', 'hold']);
});

test('PR processing targets the PR itself and linked issues', () => {
  const event = { pull_request: { number: 77, body: 'Closes #12' } };
  assert.deepEqual(targetNumbers('pull_request', event), [
    { number: 77, pullRequest: true },
    { number: 12, pullRequest: false },
  ]);
});

test('explicit Clanker PR label survives labeled events but not normal review transitions', () => {
  assert.equal(desiredState({ pullRequest: true, action: 'labeled', labels: ['3-clanker-queue'] }), '3-clanker-queue');
  assert.equal(desiredState({ pullRequest: true, action: 'opened', labels: ['3-clanker-queue'] }), '4-review');
  assert.equal(desiredState({ reviewLinkedIssue: true, action: 'opened', labels: ['3-human-queue'] }), '4-review');
});

test('issue label conflicts conservatively repair to discussion', () => {
  assert.equal(desiredState({ pullRequest: false, action: 'labeled', labels: ['3-human-queue', '3-clanker-queue'] }), '2-discussing');
});
