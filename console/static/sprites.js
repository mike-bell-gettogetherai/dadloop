/* Sprites for the house.
 *
 * Each sprite is a pixel map: rows of characters, one character per pixel, with
 * a palette mapping character to colour. Written this way rather than as path
 * data so they stay editable by hand. Add a row, change a letter, and the grill
 * changes shape.
 *
 * '.' is transparent. Everything renders as crisp rects, no anti-aliasing, so
 * the world reads as pixel art rather than as smooth vector shapes pretending.
 */

const PAL = {
  n: '#16304f',   // navy, dadloop ink
  d: '#0d1f33',   // deep shadow
  s: '#e8b48a',   // skin
  b: '#6b8fb5',   // shirt blue
  r: '#c0392b',   // trouble red
  o: '#d2601a',   // tools orange
  y: '#e0a33e',   // amber
  g: '#7d8c5c',   // sage
  w: '#fdfaf6',   // paper
  k: '#8a6d1f',   // brass dark
  m: '#8a5a3c',   // hair brown
  p: '#b5766b',   // dusty rose
  a: '#93a4b5',   // steel
  c: '#c9a24c',   // brass
  e: '#57892b',   // green
  t: '#a8845c',   // wood
};

/* Dad. The mustache is the whole brand, so it gets three pixels of its own. */
const DAD = [
  '....nnnn....',
  '...nnnnnn...',
  '..nnnnnnnn..',
  '..nssssssn..',
  '..ssssssss..',
  '..sndssdns..',
  '..ssssssss..',
  '...nnnnnn...',
  '..ssssssss..',
  '...bbbbbb...',
  '..bbbbbbbb..',
  '..bbbbbbbb..',
  '..b.bbbb.b..',
  '....nn.nn...',
];

/* Dad, mid-stride. Same head, legs crossed the other way. Alternating DAD and
 * DAD2 while he crosses the floor is the whole walk cycle: two frames is all a
 * 12-pixel man needs to look like he is going somewhere. */
const DAD2 = DAD.slice(0, 12).concat([
  '..bb.bbbb...',
  '..nn...nn...',
]);

/* Mom. Bun up top, so she reads instantly at this size even in silhouette. */
const MOM = [
  '.....mm.....',
  '....mmmm....',
  '...mmmmmm...',
  '..mmmmmmmm..',
  '..msssssm...',
  '..ssssssss..',
  '..sndssdns..',
  '..ssssssss..',
  '...ssssss...',
  '...pppppp...',
  '..pppppppp..',
  '..pppppppp..',
  '..p.pppp.p..',
  '....nn.nn...',
];

const GRILL = [
  '...o....o...',
  '....oooo....',
  '..nnnnnnnn..',
  '.nnnnnnnnnn.',
  '.nnnnnnnnnn.',
  '..nnnnnnnn..',
  '....n..n....',
  '....n..n....',
  '...nn..nn...',
];

const FRIDGE = [
  '.aaaaaaaa.',
  '.awwwwwwa.',
  '.awwwwwna.',
  '.awwwwwwa.',
  '.aaaaaaaa.',
  '.awwwwwna.',
  '.awwwwwwa.',
  '.awwwwwwa.',
  '.aaaaaaaa.',
];

const DESK = [
  '..nnnnnn..',
  '.nwwwwwwn.',
  '.nwwwwwwn.',
  '..nnnnnn..',
  'tttttttttt',
  't........t',
  't........t',
];

const TOOLBOX = [
  '....nn....',
  '...n..n...',
  'rrrrrrrrrr',
  'rrrrrrrrrr',
  'rnnnnnnnnr',
  'rrrrrrrrrr',
  'rrrrrrrrrr',
];

const DOOR = [
  'tttttttt',
  't......t',
  't......t',
  't...c..t',
  't......t',
  't......t',
  't......t',
  'tttttttt',
];

const THERMO = [
  '..aaaa..',
  '.awwwwa.',
  '.awrrwa.',
  '.awwwwa.',
  '.awwwwa.',
  '..aaaa..',
  '...aa...',
  '..aaaa..',
];

const PLANT = [
  '..e..e..',
  '.eeeeee.',
  'eeeeeeee',
  '.eeeeee.',
  '...ee...',
  '..tttt..',
  '..tttt..',
  '.tttttt.',
];

const MOWER = [
  '....nn......',
  '...nnnn.....',
  '..nnnnnnn...',
  '.rrrrrrrrr..',
  '.rrrrrrrrr..',
  '..d.....d...',
  '.dd.....dd..',
];

const SPRINKLER = [
  '..a..a..a..',
  '...a.a.a...',
  '....aaa....',
  '.....a.....',
  '....nnn....',
  '....nnn....',
];

/* The car Dad takes on a store run — parked, so the driveway reads as empty
 * when he is home and occupied when he is not, which is the whole trick for
 * showing "gone" without a second screen. */
const CAR = [
  '...nnnnnn...',
  '..nrrrrrrn..',
  '.nnnnnnnnnn.',
  'ndddddddddn.',
  'nnnnnnnnnnn.',
  '.k........k.',
];

const SPRITES = { DAD, DAD2, MOM, GRILL, FRIDGE, DESK, TOOLBOX, DOOR, THERMO, PLANT,
                  MOWER, SPRINKLER, CAR };

/* Turn a pixel map into SVG rects. `px` is the size of one pixel. */
function sprite(map, px = 3, x = 0, y = 0){
  let out = '';
  map.forEach((row, ry) => {
    let run = null;
    for(let rx = 0; rx <= row.length; rx++){
      const ch = row[rx];
      if(run && ch === run.ch){ run.len++; continue; }
      if(run){
        // merge horizontal runs into one rect: far fewer nodes, identical pixels
        out += `<rect x="${x + run.x * px}" y="${y + ry * px}" ` +
               `width="${run.len * px}" height="${px}" fill="${PAL[run.ch]}"/>`;
        run = null;
      }
      if(ch && ch !== '.') run = { ch, x: rx, len: 1 };
    }
  });
  return out;
}

function spriteWidth(map, px = 3){ return map[0].length * px; }
function spriteHeight(map, px = 3){ return map.length * px; }
