// Checks which spoken sentences are about the whiteboards, and that everything else is left alone.
import assert from 'node:assert/strict';
import { parseBoardCommand, findByName, normalize } from '../../web/boards.js';

const ok = (name) => console.log(`ok   ${name}`);
const names = ['Main', 'Work', 'Work stuff', 'Recipes', 'Board 2', 'Home Lab'];
const cmd = (text) => parseBoardCommand(text, names);

assert.equal(normalize('Board Two!'), 'board 2');
assert.equal(findByName('recipes', names), 'Recipes');
assert.equal(findByName('home', names), 'Home Lab');                 // the first words of one board's name
assert.equal(findByName('work', names), 'Work');                     // an exact name wins over "Work stuff"
assert.equal(findByName('board two', names), 'Board 2');
assert.equal(findByName('wor', names), null);
assert.equal(findByName('', names), null);
ok('names are matched by words, exactly or by their first words when only one fits');

for (const [say, want] of [
  ['go to the work board', { op: 'switch', name: 'Work' }],
  ['Jarvis, switch to recipes', { op: 'switch', name: 'Recipes' }],
  ['please switch to the home lab board', { op: 'switch', name: 'Home Lab' }],
  ['switch to board two', { op: 'switch', name: 'Board 2' }],
  ['open the recipes board', { op: 'switch', name: 'Recipes' }],
  ['show me the work whiteboard', { op: 'switch', name: 'Work' }],
  ['go back to main', { op: 'switch', name: 'Main' }],
  ['go to the banana board', { op: 'missing', name: 'banana' }],
  ['next board', { op: 'next' }],
  ['go to the next whiteboard', { op: 'next' }],
  ['previous screen', { op: 'previous' }],
  ['switch to the last board', { op: 'previous' }],
  ['make a new board called pizza night', { op: 'new', name: 'Pizza Night' }],
  ['create a new whiteboard named Plans', { op: 'new', name: 'Plans' }],
  ['new board', { op: 'new', name: '' }],
  ['Jarvis, add another new board', { op: 'new', name: '' }],
  ['rename this board to Ideas', { op: 'rename', name: 'Ideas' }],
  ['call this board shopping list', { op: 'rename', name: 'Shopping List' }],
  ['what boards do I have', { op: 'list' }],
  ['list my boards', { op: 'list' }],
  ['which board is this', { op: 'which' }],
  ['what board am I on', { op: 'which' }],
]) assert.deepEqual(cmd(say), want, say);
ok('sentences about the boards are understood');

for (const no of ['go to sleep', 'switch to the lights', 'open spotify', 'open the recipes', 'show me a picture of a cat', 'show the board', 'what time is it', 'play some music',
  'go to youtube.com', 'turn the lights off', 'new note buy milk', 'rename the file', 'show me my notes', 'switch to', '', 'open the board', 'what is this', 'delete the work board',
  'remove this board']) assert.equal(cmd(no), null, no);
ok('everything else is left for the other commands (and deleting is never done by voice)');
