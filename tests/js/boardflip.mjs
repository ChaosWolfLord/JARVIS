// Checks where each board's card is in the switch animation: at rest only the current board shows; in the showcase the board you are on has pulled back
// with the others tilted beside it; when it flies forward the chosen one comes to full size and the rest sink away.
import assert from 'node:assert/strict';
import { cardPose, TIMING } from '../../web/boardflip.js';

const ok = (name) => console.log(`ok   ${name}`);
const base = { current: 1, target: 3, w: 1920, h: 1080 };

const rest = [0, 1, 2, 3].map((i) => cardPose({ ...base, phase: 'idle', i, focus: 1 }));
assert.deepEqual(rest.map((p) => p.o), [0, 1, 0, 0]);
assert.equal(rest[1].s, 1);
assert.equal(rest[1].z, 0);
ok('at rest only the board you are on is there, full size');

const back = [0, 1, 2, 3].map((i) => cardPose({ ...base, phase: 'back', i, focus: 1 }));
assert.ok(back[1].s < 0.5 && back[1].s > 0.4, 'the board you are on pulls back');
assert.equal(back[1].x, 0);
assert.ok(back[1].z < 0, 'and moves away from you');
assert.equal(back[1].o, 1);
assert.ok(back[2].x > 0 && back[0].x < 0, 'the others sit beside it');
assert.ok(back[2].r < 0 && back[0].r > 0, 'tilted towards it');
assert.ok(back[2].o < 1 && back[2].o > 0, 'and dimmer');
assert.ok(back[1].label > 0, 'the names show in the showcase');
assert.equal(back[1].ms, TIMING.back);
ok('the board you are on pulls back into a row of boards');

const slid = [0, 1, 2, 3].map((i) => cardPose({ ...base, phase: 'showcase', i, focus: 3 }));
assert.equal(slid[3].x, 0);
assert.ok(slid[1].x < 0 && slid[0].x < slid[1].x, 'the row slides so the chosen board is in the middle');
assert.equal(slid[0].o, 0, 'a board more than two places from the middle fades out');
assert.equal(slid[3].ms, TIMING.slide);
ok('the row slides to the board you chose');

const fly = [0, 1, 2, 3].map((i) => cardPose({ ...base, phase: 'fly', i, focus: 3 }));
assert.deepEqual([fly[3].x, fly[3].z, fly[3].r, fly[3].s, fly[3].o], [0, 0, 0, 1, 1]);
assert.ok(fly[3].flat, 'the landing card becomes the board itself');
assert.ok(fly.filter((_, i) => i !== 3).every((p) => p.o === 0 && p.z < 0), 'the others sink away');
assert.equal(fly[3].ms, TIMING.fly);
assert.ok(TIMING.fly > TIMING.slide, 'the flight is the long, gentle part');
ok('the chosen board flies forward to full size and the others sink away');

const wide = cardPose({ ...base, w: 3840, phase: 'back', i: 2, focus: 1 });
const narrow = cardPose({ ...base, w: 1920, phase: 'back', i: 2, focus: 1 });
assert.equal(wide.x, narrow.x * 2);
ok('a wider board spaces its cards out in proportion');
