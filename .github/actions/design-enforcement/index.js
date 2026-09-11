const fs = require('node:fs');

const WORKFLOW_LABELS = [
  '1-triage',
  '2-discussing',
  '3-human-queue',
  '3-clanker-queue',
  '4-review',
  'blocked',
  'hold',
];
const PRIMARY_LABELS = WORKFLOW_LABELS.slice(0, 5);
const ANNOUNCEMENT_MARKER = '<!-- design-enforcement:clanker-announcement -->';
const CORRECTIVE_MARKER = '<!-- design-enforcement:corrective -->';

function parseIssueNumbers(body = '') {
  const numbers = [];
  const reference = /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:https:\/\/github\.com\/[^/]+\/[^/]+\/issues\/)?#?(\d+)/gi;
  let match;
  while ((match = reference.exec(body)) !== null) numbers.push(Number(match[1]));
  return [...new Set(numbers)];
}

function fieldValues(body = '') {
  const values = new Map();
  const heading = /^#{2,6}\s+(.+?)\s*$/gm;
  const matches = [...body.matchAll(heading)];
  for (let i = 0; i < matches.length; i += 1) {
    const name = matches[i][1].trim();
    const start = matches[i].index + matches[i][0].length;
    const end = matches[i + 1]?.index ?? body.length;
    values.set(name.toLowerCase(), body.slice(start, end).trim());
  }
  return values;
}

function hasValidOptIn(body, requiredGroups) {
  const checkedOptIn = body.split('\n').some((line) => /-\s*\[[xX]\]/.test(line) && /clanker|community army/i.test(line));
  if (!checkedOptIn) return false;
  const fields = fieldValues(body);
  return requiredGroups.every((group) => group.some((name) => {
    const value = fields.get(String(name).toLowerCase());
    return value && !/^_?no response_?$/i.test(value) && !/^<!--.*-->$/.test(value);
  }));
}

function chooseState(labels) {
  const primary = labels.filter((label) => PRIMARY_LABELS.includes(label));
  return primary.length === 1 ? primary[0] : '2-discussing';
}

function canonicalLabels(labels, state) {
  const desired = state || chooseState(labels);
  const overlay = labels.includes('blocked') ? 'blocked' : labels.includes('hold') ? 'hold' : null;
  return [desired, overlay].filter(Boolean);
}

function targetNumbers(eventName, event) {
  if (eventName !== 'pull_request' && eventName !== 'pull_request_target') {
    return event.issue?.number ? [{ number: event.issue.number, pullRequest: false }] : [];
  }
  const pullRequest = event.pull_request || {};
  return [
    { number: pullRequest.number, pullRequest: true },
    ...parseIssueNumbers(pullRequest.body || '').map((number) => ({ number, pullRequest: false })),
  ].filter((target, index, all) => target.number && all.findIndex((item) => item.number === target.number) === index);
}

function desiredState({
  pullRequest,
  reviewLinkedIssue = false,
  action,
  labels,
  issueBody = '',
  isNewIssue = false,
  requiredGroups = [],
}) {
  if (pullRequest) {
    if (action === 'labeled' && labels.includes('3-clanker-queue')) return '3-clanker-queue';
    return '4-review';
  }
  if (reviewLinkedIssue) return '4-review';
  const primary = labels.filter((label) => PRIMARY_LABELS.includes(label));
  if (primary.length !== 1) {
    return isNewIssue && primary.length === 0 && hasValidOptIn(issueBody, requiredGroups)
      ? '3-clanker-queue'
      : '2-discussing';
  }
  if (isNewIssue) return hasValidOptIn(issueBody, requiredGroups) ? '3-clanker-queue' : '1-triage';
  return chooseState(labels);
}

function buildAnnouncement(url, issueNumber) {
  return `This issue is now in the \`clanker-queue\` and will be doled out to the community army. Check ${url} to find out more. Good Hunting.\n\nNext action: follow the issue acceptance criteria and open a pull request with \`Closes #${issueNumber}\`.\n\n${ANNOUNCEMENT_MARKER}`;
}

function buildCorrectionComment(state) {
  return `The workflow labels were repaired to \`${state}\`. Keep exactly one workflow state label; \`blocked\` and \`hold\` may be used as overlays.\n\n${CORRECTIVE_MARKER}`;
}

async function main() {
  const token = process.env.GITHUB_TOKEN;
  const repository = process.env.GITHUB_REPOSITORY;
  if (!token || !repository) throw new Error('GITHUB_TOKEN and GITHUB_REPOSITORY are required');
  const [owner, repo] = repository.split('/');
  const api = async (method, path, body) => {
    const response = await fetch(`https://api.github.com${path}`, {
      method,
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
    return response.status === 204 ? null : response.json();
  };

  const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  const eventName = process.env.GITHUB_EVENT_NAME;
  const requiredGroups = JSON.parse(process.env.INPUT_REQUIRED_FIELD_GROUPS || '[]');
  const contributeUrl = process.env.INPUT_HIVE_CONTRIBUTE_URL || 'https://kubestellar.io/live/hive/bluefin/';
  const isNewIssue = eventName === 'issues' && event.action === 'opened';
  const targets = targetNumbers(eventName, event);

  for (const target of targets) {
    const issue = await api('GET', `/repos/${owner}/${repo}/issues/${target.number}`);
    const current = issue.labels.map((label) => typeof label === 'string' ? label : label.name);
    const desired = desiredState({
      pullRequest: target.pullRequest,
      reviewLinkedIssue: !target.pullRequest && targets[0]?.pullRequest === true,
      action: event.action,
      labels: current,
      issueBody: issue.body || '',
      isNewIssue,
      requiredGroups,
    });
    const labels = canonicalLabels(current, desired);
    if (labels.sort().join('\n') !== current.sort().join('\n')) {
      await api('PUT', `/repos/${owner}/${repo}/issues/${target.number}/labels`, { labels });
    }

    const comments = await api('GET', `/repos/${owner}/${repo}/issues/${target.number}/comments?per_page=100`);
    const bodies = comments.map((comment) => comment.body || '');
    const invalid = current.filter((label) => PRIMARY_LABELS.includes(label)).length !== 1;
    if (!target.pullRequest && invalid && desired === '2-discussing' && !bodies.some((body) => body.includes(CORRECTIVE_MARKER))) {
      await api('POST', `/repos/${owner}/${repo}/issues/${target.number}/comments`, { body: buildCorrectionComment(desired) });
    }
    if (!target.pullRequest && desired === '3-clanker-queue' && !bodies.some((body) => body.includes(ANNOUNCEMENT_MARKER))) {
      await api('POST', `/repos/${owner}/${repo}/issues/${target.number}/comments`, { body: buildAnnouncement(contributeUrl, target.number) });
    }
  }
}

module.exports = {
  ANNOUNCEMENT_MARKER,
  CORRECTIVE_MARKER,
  PRIMARY_LABELS,
  WORKFLOW_LABELS,
  parseIssueNumbers,
  hasValidOptIn,
  chooseState,
  canonicalLabels,
  targetNumbers,
  desiredState,
  buildAnnouncement,
  buildCorrectionComment,
  main,
};

if (require.main === module) main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
