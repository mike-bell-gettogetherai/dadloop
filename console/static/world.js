/* The house, as a pixel world under a real sky.
 *
 * Rooms are tiled floors with a prop in each. Dad walks to whichever room the
 * current tool call is happening in and says what he is doing. Mom appears in a
 * doorway only when a policy actually stopped something.
 *
 * Two things here are driven by REAL data rather than decoration, which is the
 * whole dadloop ethos carried into the picture:
 *
 *   The sky. Every journal event carries a timestamp, so the strip above the
 *   house shows the actual time of the turn: first light, full day, a dusk
 *   gradient, or night with stars and a moon. A cookout planned at 9pm looks
 *   like 9pm.
 *
 *   The weather. When Dad calls check_weather, the result text is read for
 *   rain / storm / cloud / clear / heat, and the sky answers: drops fall, a
 *   cloud drifts in, the sun comes out. Nothing is drawn that the harness did
 *   not actually learn.
 *
 * Dad is the one thing NOT redrawn every frame. He lives in a persistent <g>
 * whose transform is updated in place, so the CSS transition can carry him
 * across the floor. Redrawing him would snap him room to room; keeping the
 * element lets him walk.
 */

const W = 640, SKY = 44, H = 430 + SKY, TILE = 10;

// Room geometry, shifted down by the sky strip.
const ROOMS = [
  { id:'grill',   name:'Backyard',  x: 16, y: 16, w:126, h:126, prop:'GRILL',   outside:true },
  { id:'pantry',  name:'Kitchen',   x:150, y: 16, w:126, h:126, prop:'FRIDGE'  },
  { id:'weather', name:'Porch',     x:284, y: 16, w:126, h:126, prop:'PLANT',   outside:true },
  { id:'lawn',    name:'Lawn',      x:418, y: 16, w:206, h:126, prop:'MOWER',   outside:true },
  { id:'budget',  name:'Study',     x: 16, y:150, w:126, h:126, prop:'DESK'    },
  { id:'tools',   name:'Garage',    x:150, y:150, w:126, h:126, prop:'TOOLBOX' },
  { id:'store',   name:'Driveway',  x:284, y:150, w:340, h:126, prop:'CAR',     outside:true, driveway:true },
  { id:'hall',    name:'Hallway',   x: 16, y:284, w:608, h:120, prop:'THERMO'  },
].map(r => ({ ...r, y: r.y + SKY }));
const ROOM_BY_ID = Object.fromEntries(ROOMS.map(r => [r.id, r]));

const FLOOR = { indoor:['#e8d8ba','#dccaa6'], outdoor:['#bcd29b','#aec686'] };
const LIT   = { indoor:['#fae5b8','#f0d7a4'], outdoor:['#dee9b4','#d0dc9d'] };
const BAD   = { indoor:['#f3cdc3','#e9bdb1'], outdoor:['#e5c7ba','#d9b6a7'] };
const GOV   = { indoor:['#f2e6c4','#ece0b8'], outdoor:['#e6dcb4','#dfd5aa'] };

// ------------------------------------------------------------------ sky
/* Four looks, chosen by the hour the turn actually happened. Each is a
 * two-stop vertical gradient plus what hangs in it. */
function skyFor(hour){
  if(hour >= 5  && hour < 8)  return { top:'#f6c99a', bot:'#fbe4c2', sun:{x:80,  y:30, c:'#f5a623'}, name:'dawn' };
  if(hour >= 8  && hour < 17) return { top:'#a9d3ee', bot:'#d9ecf7', sun:{x:560, y:22, c:'#f7d154'}, name:'day' };
  if(hour >= 17 && hour < 20) return { top:'#8a6fb5', bot:'#f2a973', sun:{x:120, y:36, c:'#f08a4b'}, name:'dusk' };
  return { top:'#0d1b33', bot:'#1e2d4f', moon:{x:560, y:20}, stars:true, name:'night' };
}

function drawSky(hour, weather, when){
  const s = skyFor(hour);
  let out = `<defs><linearGradient id="skyg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${s.top}"/><stop offset="1" stop-color="${s.bot}"/>
    </linearGradient></defs>
    <rect x="0" y="0" width="${W}" height="${SKY}" fill="url(#skyg)"/>`;

  if(s.stars){
    // A fixed scatter, so the night sky is the same night sky on every replay.
    const pts = [[22,9],[61,25],[113,7],[160,30],[228,12],[271,28],[338,8],[402,24],[451,6],[497,31],[612,11]];
    out += pts.map(([x,y]) => `<rect x="${x}" y="${y}" width="2" height="2" fill="#e9eefc"/>`).join('');
    out += `<circle cx="${s.moon.x}" cy="${s.moon.y}" r="9" fill="#f2efdc"/>
            <circle cx="${s.moon.x-4}" cy="${s.moon.y-2}" r="8" fill="${s.top}"/>`;
  } else if(s.sun && weather !== 'rain' && weather !== 'storm'){
    out += `<circle cx="${s.sun.x}" cy="${s.sun.y}" r="9" fill="${s.sun.c}"/>`;
  }

  // Weather, only if check_weather actually reported it this session.
  if(weather === 'cloud' || weather === 'rain' || weather === 'storm'){
    const cx = 300, cy = 20;
    const cc = weather === 'cloud' ? '#f7f5ef' : '#b9bcc7';
    out += `<g fill="${cc}"><rect x="${cx-22}" y="${cy}" width="44" height="12" rx="6"/>
            <circle cx="${cx-8}" cy="${cy-2}" r="9"/><circle cx="${cx+6}" cy="${cy-4}" r="11"/></g>`;
    if(weather !== 'cloud'){
      const drops = [[-16,16],[-6,20],[4,15],[14,21],[24,17]];
      out += drops.map(([dx,dy]) =>
        `<rect x="${cx+dx}" y="${cy+dy}" width="2" height="6" fill="#6f8fc4" class="drop"/>`).join('');
    }
    if(weather === 'storm') out += `<path d="M${cx+34},${cy-2} l-6,10 h6 l-6,12" stroke="#f7d154" stroke-width="2" fill="none"/>`;
  }
  if(weather === 'hot'){
    out += `<text x="${s.sun ? s.sun.x + 16 : 40}" y="${(s.sun ? s.sun.y : 30) + 4}" class="skytxt" fill="#c0392b">heat advisory</text>`;
  }

  const tint = s.stars ? '#e4e6ee' : '#2d3a4f';
  out += `<text x="8" y="14" class="skytxt" fill="${tint}">${escapeXml(when || '')}</text>`;
  out += `<text x="${W-8}" y="${SKY-8}" text-anchor="end" class="skytxt" fill="${tint}">${s.name}${weather ? ' \u00b7 ' + weather : ''}</text>`;
  return out;
}

/* Read a check_weather result for the one word that matters. Order matters:
 * "storm" beats "rain" beats "cloud"; "clear" and "sun" mean sun. */
function weatherFrom(text){
  const t = (text || '').toLowerCase();
  if(/thunder|storm/.test(t)) return 'storm';
  if(/rain|shower|drizzle/.test(t)) return 'rain';
  if(/heat advisory|\b9\d\s*°?f\b|scorch/.test(t)) return 'hot';
  if(/cloud|overcast/.test(t)) return 'cloud';
  if(/clear|sunny|sun\b/.test(t)) return 'clear';
  return null;
}

// ----------------------------------------------------------------- rooms
function tiles(r, pal){
  let out = '';
  for(let y = 0; y < r.h; y += TILE){
    for(let x = 0; x < r.w; x += TILE){
      const alt = ((x / TILE | 0) + (y / TILE | 0)) % 2;
      const w = Math.min(TILE, r.w - x), h = Math.min(TILE, r.h - y);
      out += `<rect x="${r.x + x}" y="${r.y + y}" width="${w}" height="${h}" fill="${pal[alt]}"/>`;
    }
  }
  return out;
}

/* A speech bubble anchored at (x, y), the top-centre of a sprite. The tail
 * stays on the speaker; the box slides sideways so it never runs off the edge. */
function bubble(x, y, text){
  if(!text) return '';
  const t = text.length > 34 ? text.slice(0, 33) + '\u2026' : text;
  const w = Math.max(52, t.length * 5.4 + 14);
  const bx = Math.min(Math.max(x - w/2, 6), W - w - 6);
  return `<g class="bub">
    <rect x="${bx}" y="${y - 26}" width="${w}" height="19" rx="2"
          fill="#fdfaf6" stroke="#16304f" stroke-width="1.5"/>
    <path d="M${x-4},${y-7} L${x},${y-2} L${x+4},${y-7} Z" fill="#fdfaf6"
          stroke="#16304f" stroke-width="1.5" stroke-linejoin="miter"/>
    <text x="${bx + w/2}" y="${y - 13}" text-anchor="middle" class="bubtxt">${escapeXml(t)}</text>
  </g>`;
}
const escapeXml = s => String(s == null ? '' : s)
  .replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

/* Everything except Dad: sky, rooms, props, captions, Mom. Redrawn per frame.
 * state: { roomStates, details, dadRoom, dadSays, dadOut, momRoom, momSays,
 *          hour, weather, when } */
function drawWorld(state){
  let svg = drawSky(state.hour ?? 12, state.weather, state.when);
  const night = (state.hour ?? 12) >= 20 || (state.hour ?? 12) < 5;
  svg += `<rect x="0" y="${SKY}" width="${W}" height="${H-SKY}" fill="${night ? '#8f8368' : '#c8b795'}"/>`;

  ROOMS.forEach(r => {
    const st = state.roomStates[r.id];
    const kind = r.outside ? 'outdoor' : 'indoor';
    // A room that JUST turned to trouble gets a shake. It is a fresh element
    // every frame, so the animation fires exactly once: on the frame it broke.
    const shake = (state.justBroke || []).includes(r.id) ? ' class="shake"' : '';
    svg += `<g${shake}>`;
    const pal = st === 'trouble' ? BAD[kind]
              : st === 'governed' ? GOV[kind]
              : st === 'lit' ? LIT[kind] : FLOOR[kind];
    svg += tiles(r, pal);
    // At night, rooms nobody is working in sit in shadow; a lit room is a lamp on.
    if(night && !st) svg += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="#0d1b33" opacity=".38"/>`;

    const stroke = st === 'trouble' ? '#c0392b' : st === 'governed' ? '#c9a24c'
                 : st === 'lit' ? '#d2601a' : '#16304f';
    svg += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="none"
             stroke="${stroke}" stroke-width="${st ? 3 : 2}"/>`;

    if(r.driveway){
      if(!state.dadOut){
        svg += sprite(CAR, 4, r.x + r.w - spriteWidth(CAR, 4) - 20, r.y + r.h - spriteHeight(CAR, 4) - 14);
      } else {
        svg += `<text x="${r.x + r.w - 20}" y="${r.y + r.h - 30}" text-anchor="end" class="rmdet">car gone</text>`;
      }
    } else {
      const map = SPRITES[r.prop];
      if(map) svg += sprite(map, 4, r.x + 16, r.y + r.h - spriteHeight(map, 4) - 30);
    }
    svg += `<text x="${r.x + 8}" y="${r.y + 15}" class="rmname">${r.name.toUpperCase()}</text>`;
    const det = state.details[r.id];
    if(det) svg += `<text x="${r.x + 8}" y="${r.y + r.h - 6}" class="rmdet">${escapeXml(det)}</text>`;
    svg += `</g>`;
  });

  // ---- light across the whole scene, not just the sky strip -----------
  // Dusk throws a warm wash over everything; night pulls the lot down to
  // blue and lets the rooms Dad has touched glow like a lamp left on.
  const hr = state.hour ?? 12;
  if(hr >= 17 && hr < 20)
    svg += `<rect x="0" y="${SKY}" width="${W}" height="${H-SKY}" fill="#f08a4b" opacity=".12"/>`;
  if(night){
    svg += `<defs><radialGradient id="glow"><stop offset="0" stop-color="#ffd47a" stop-opacity=".55"/>
              <stop offset="1" stop-color="#ffd47a" stop-opacity="0"/></radialGradient></defs>`;
    ROOMS.forEach(r => {
      if(state.roomStates[r.id] === 'lit' || state.roomStates[r.id] === 'governed')
        svg += `<ellipse cx="${r.x + r.w/2}" cy="${r.y + r.h/2}" rx="${r.w*0.7}" ry="${r.h*0.7}" fill="url(#glow)" class="glow"/>`;
    });
  }
  // Rain falls on the yard, not only in the sky. Fixed scatter, so replay is
  // deterministic; the CSS animation gives each drop its fall.
  if(state.weather === 'rain' || state.weather === 'storm'){
    let seed = 7;
    const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    ROOMS.filter(r => r.outside).forEach(r => {
      const n = Math.round(r.w * r.h / 1400);
      for(let i = 0; i < n; i++)
        svg += `<rect x="${Math.round(r.x + 4 + rnd()*(r.w-8))}" y="${Math.round(r.y + 4 + rnd()*(r.h-14))}"
                 width="2" height="6" fill="#6f8fc4" class="drop" style="animation-delay:${(rnd()*0.9).toFixed(2)}s"/>`;
    });
  }
  // Smoke off a lit grill. Three puffs on a loop, rising and fading.
  if(state.roomStates.grill === 'lit'){
    const g = ROOM_BY_ID.grill, gx = g.x + 16 + 24, gy = g.y + g.h - spriteHeight(GRILL,4) - 34;
    [0,1,2].forEach(i =>
      svg += `<rect x="${gx + i*5}" y="${gy}" width="4" height="4" fill="#9aa1a8" class="smoke" style="animation-delay:${i*0.5}s"/>`);
  }

  if(state.dadOut){
    const dr = ROOM_BY_ID.store;
    svg += `<text x="${dr.x + 16}" y="${dr.y + 40}" class="rmdet" font-style="italic">out at the hardware store\u2026</text>`;
  }
  if(state.momRoom && ROOM_BY_ID[state.momRoom]){
    const mr = ROOM_BY_ID[state.momRoom];
    const mx = mr.x + 26 + spriteWidth(SPRITES[mr.prop] || DAD, 4);
    const my = mr.y + mr.h - spriteHeight(MOM, 4) - 26;
    svg += `<g class="actor mom-in">` + sprite(MOM, 4, mx, my) + `</g>`;
    svg += bubble(mx + spriteWidth(MOM, 4) / 2, my, state.momSays || 'Not so fast.');
  }
  return svg;
}

/* Where Dad stands for a given room. */
function dadSpot(state){
  const dr = ROOM_BY_ID[state.dadRoom] || ROOM_BY_ID.hall;
  return { x: dr.x + dr.w - 74, y: dr.y + dr.h - spriteHeight(DAD, 4) - 26 };
}

/* Dad lives in a persistent #dad group. Only his transform and his bubble
 * change between frames, so the CSS transition on the group walks him across
 * the floor instead of teleporting. */
function placeDad(state){
  const g = document.getElementById('dad');
  if(!g) return;
  const b = document.getElementById('dadbub');
  if(state.dadOut){
    g.style.opacity = 0;
    if(b) b.innerHTML = '';        // a bubble with nobody under it is a lie
    return;
  }
  g.style.opacity = 1;
  const { x, y } = dadSpot(state);
  if(!g.dataset.drawn){
    g.innerHTML = `<g class="f1">${sprite(DAD, 4, 0, 0)}</g><g class="f2">${sprite(DAD2, 4, 0, 0)}</g>`;
    g.dataset.drawn = '1';
  }
  const next = `translate(${x}px, ${y}px)`;
  if(g.style.transform && g.style.transform !== next){
    // He is about to cross the floor: swing the legs for the length of the
    // transition, then stand still. Facing flips with direction of travel.
    g.classList.add('walking');
    const prevX = parseFloat((g.style.transform.match(/translate\(([-\d.]+)px/) || [])[1] || x);
    g.classList.toggle('faceleft', x < prevX);
    clearTimeout(g._walkT);
    g._walkT = setTimeout(() => g.classList.remove('walking'), 900);
  }
  g.style.transform = next;
  // The bubble is not inside the moving group: it is re-anchored so it clamps
  // to the canvas edge correctly rather than moving with the sprite.
  const sharing = state.momRoom && state.momRoom === (state.dadRoom || 'hall');
  if(b) b.innerHTML = bubble(x + spriteWidth(DAD, 4) / 2, y - (sharing ? 24 : 0), state.dadSays);
}
