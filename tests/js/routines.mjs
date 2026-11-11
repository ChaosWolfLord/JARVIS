// The page and the PC must agree on which sentence starts which routine: both are checked against the same list (tests/fixtures/routine_phrases.json).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.document = { createElement: () => ({}) };
const { normalize, plain, matchRoutine, Routines } = await import('../../web/routines.js');
const ok = (name) => console.log(`ok   ${name}`);
const fixture = JSON.parse(readFileSync(new URL('../fixtures/routine_phrases.json', import.meta.url), 'utf8'));

for (const [said, want] of fixture.normalize) assert.equal(normalize(said), want, JSON.stringify(said));
for (const [said, want] of fixture.plain) assert.equal(plain(said), want, JSON.stringify(said));
ok('the page reads sentences exactly as the PC does');

const routines = [{ id: 'a1', name: 'Movie night', phrases: ['film time', 'start the movie'], steps: ['x'] }, { id: 'b2', name: 'Goodnight', phrases: [], steps: ['y'] }];
for (const yes of ['movie night', 'Jarvis, start the movie night routine', 'film time', 'Jarvis, film time please', 'start the movie', 'goodnight', 'activate goodnight mode']) {
  assert.ok(matchRoutine(yes, routines), yes);
}
for (const no of ['movie', 'night', 'play a movie', 'turn off the lights', 'what is the time', 'good night', '', 'movie night tomorrow please remind me', 'start film time', 'film', "it's film time"]) {
  assert.equal(matchRoutine(no, routines), null, no);
}
ok('a name is understood in many ways, an extra phrase only as written');

const stub = () => ({ addEventListener() {}, textContent: '', querySelector: () => null });
const root = { querySelector: () => stub() };
const ui = new Routines({ root });
ui.routines = routines;
const ran = [];
ui.run = (id) => ran.push(id);
assert.equal(ui.handleVoice('movie night'), true);
assert.equal(ui.handleVoice('what is the weather'), false);
assert.deepEqual(ran, ['a1']);
ok('saying a routine runs it, and other sentences are left alone');
