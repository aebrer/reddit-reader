const assert = require('node:assert/strict');
const { test, afterEach } = require('node:test');
const { pageIsReady } = require('../scripts/browser_fetch.cjs');

afterEach(() => { delete global.document; });

test('challenge navigation can temporarily have no body', () => {
  global.document = { body: null };
  assert.equal(pageIsReady('target'), false);
});

test('post header alone is not enough for a comment permalink', () => {
  global.document = {
    body: { innerText: 'Post header' },
    querySelector: (selector) => selector === 'shreddit-post' ? {} : null,
  };
  assert.equal(pageIsReady('target'), false);
});

test('waits for the exact requested comment body', () => {
  global.document = {
    body: { innerText: 'Post and comments' },
    querySelector: (selector) => ['shreddit-post',
      'shreddit-comment[thingid="t1_target"] [slot="comment"]'].includes(selector) ? {} : null,
  };
  assert.equal(pageIsReady('target'), true);
  assert.equal(pageIsReady('missing'), false);
});

test('network block can be reported without waiting for a timeout', () => {
  global.document = { body: { innerText: "You've been blocked by network security." } };
  assert.equal(pageIsReady('target'), true);
});

test('zero-comment posts do not require a comment body', () => {
  global.document = {
    body: { innerText: 'No comments yet' },
    querySelector: (selector) => selector === 'shreddit-post' ? {
      getAttribute: () => '0',
    } : null,
  };
  assert.equal(pageIsReady(), true);
});
