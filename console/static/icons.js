/* Lucide icons, used in the editorial column and the dock.
 *
 * Path data is lifted verbatim from lucide-icons/lucide (ISC licensed). Only the
 * drawing elements are kept; the wrapper is rebuilt here so size and stroke are
 * ours to control.
 *
 * Deliberately NOT used inside the house. That view renders with crisp edges at
 * a 4px grid, and Lucide's smooth 2px rounded strokes would read as a mistake
 * next to it. Line icons belong to the dadloop editorial layer, which is where
 * the rest of the brand already uses them.
 *
 * Animation is CSS, not Motion. The handful of moments worth animating (a tool
 * running, a milestone being selected) are a spin and a draw-in, which do not
 * justify a React and Motion dependency in a console that otherwise has no
 * build step at all.
 */

const LUCIDE = {
 "flag": "<path d=\"M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528\" />",
 "triangle-alert": "<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\" /><path d=\"M12 9v4\" /><path d=\"M12 17h.01\" />",
 "shield-check": "<path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\" /><path d=\"m9 12 2 2 4-4\" />",
 "git-compare-arrows": "<circle cx=\"5\" cy=\"6\" r=\"3\" /><path d=\"M12 6h5a2 2 0 0 1 2 2v7\" /><path d=\"m15 9-3-3 3-3\" /><circle cx=\"19\" cy=\"18\" r=\"3\" /><path d=\"M12 18H7a2 2 0 0 1-2-2V9\" /><path d=\"m9 15 3 3-3 3\" />",
 "circle-check": "<circle cx=\"12\" cy=\"12\" r=\"10\" /><path d=\"m16 9-5.5 5.5L8 12\" />",
 "loader-circle": "<path d=\"M21 12a9 9 0 1 1-6.219-8.56\" />",
 "book-open-text": "<path d=\"M12 5v16\" /><path d=\"M16 13h2\" /><path d=\"M16 9h2\" /><path d=\"M20.001 19A2 2 0 0022 17V5a2 2 0 00-1.999-2L16 3.002A5 5 0 0012 5a5 5 0 00-4-2H4a2 2 0 00-2 2v12a2 2 0 001.999 2H8a5 5 0 014 2 5 5 0 014-2z\" /><path d=\"M6 13h2\" /><path d=\"M6 9h2\" />",
 "scroll-text": "<path d=\"M15 12h-5\" /><path d=\"M15 8h-5\" /><path d=\"M19 17V5a2 2 0 0 0-2-2H4\" /><path d=\"M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3\" />",
 "users-round": "<path d=\"M18 21a8 8 0 0 0-16 0\" /><circle cx=\"10\" cy=\"8\" r=\"5\" /><path d=\"M22 20c0-3.37-2-6.5-4-8a5 5 0 0 0-.45-8.3\" />",
 "message-square-quote": "<path d=\"M14 14a2 2 0 0 0 2-2V8h-2\" /><path d=\"M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z\" /><path d=\"M8 14a2 2 0 0 0 2-2V8H8\" />",
 "package-open": "<path d=\"M12 22v-9\" /><path d=\"M15.17 2.21a1.67 1.67 0 0 1 1.63 0L21 4.57a1.93 1.93 0 0 1 0 3.36L8.82 14.79a1.655 1.655 0 0 1-1.64 0L3 12.43a1.93 1.93 0 0 1 0-3.36z\" /><path d=\"M20 13v3.87a2.06 2.06 0 0 1-1.11 1.83l-6 3.08a1.93 1.93 0 0 1-1.78 0l-6-3.08A2.06 2.06 0 0 1 4 16.87V13\" /><path d=\"M21 12.43a1.93 1.93 0 0 0 0-3.36L8.83 2.2a1.64 1.64 0 0 0-1.63 0L3 4.57a1.93 1.93 0 0 0 0 3.36l12.18 6.86a1.636 1.636 0 0 0 1.63 0z\" />",
 "wallet": "<path d=\"M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1\" /><path d=\"M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4\" />",
 "sprout": "<path d=\"M14 9.536V7a4 4 0 0 1 4-4h1.5a.5.5 0 0 1 .5.5V5a4 4 0 0 1-4 4 4 4 0 0 0-4 4c0 2 1 3 1 5a5 5 0 0 1-1 3\" /><path d=\"M4 9a5 5 0 0 1 8 4 5 5 0 0 1-8-4\" /><path d=\"M5 21h14\" />",
 "flame": "<path d=\"M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4\" />",
 "refrigerator": "<path d=\"M5 6a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6Z\" /><path d=\"M5 10h14\" /><path d=\"M15 7v6\" />",
 "door-open": "<path d=\"M11 20H2\" /><path d=\"M11 4.562v16.157a1 1 0 0 0 1.242.97L19 20V5.562a2 2 0 0 0-1.515-1.94l-4-1A2 2 0 0 0 11 4.561z\" /><path d=\"M11 4H8a2 2 0 0 0-2 2v14\" /><path d=\"M14 12h.01\" /><path d=\"M22 20h-3\" />",
 "cloud-sun": "<path d=\"M12 2v2\" /><path d=\"m4.93 4.93 1.41 1.41\" /><path d=\"M20 12h2\" /><path d=\"m19.07 4.93-1.41 1.41\" /><path d=\"M15.947 12.65a4 4 0 0 0-5.925-4.128\" /><path d=\"M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z\" />",
 "wrench": "<path d=\"M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z\" />",
 "search": "<path d=\"m21 21-4.34-4.34\" /><circle cx=\"11\" cy=\"11\" r=\"8\" />",
 "thermometer": "<path d=\"M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z\" />",
 "activity": "<path d=\"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2\" />",
 "clipboard-list": "<rect width=\"8\" height=\"4\" x=\"8\" y=\"2\" rx=\"1\" ry=\"1\" /><path d=\"M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2\" /><path d=\"M12 11h4\" /><path d=\"M12 16h4\" /><path d=\"M8 11h.01\" /><path d=\"M8 16h.01\" />"
};

/* icon(name, opts) -> inline svg string.
 * `cls` rides on the svg so CSS can animate individual icons.
 */
function icon(name, { size = 14, cls = '', stroke = 1.8 } = {}){
  const body = LUCIDE[name];
  if(!body) return '';
  return `<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" stroke-width="${stroke}"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

/* Which icon stands for which milestone. Falls back to a dot when a new
 * milestone type appears that this map has not caught up with. */
const MILESTONE_ICON = {
  GOAL_FRAMED:       'flag',
  WORLD_CHECKED:     'search',
  CONSTRAINT_FOUND:  'triangle-alert',
  CONSTRAINT_CLEARED:'circle-check',
  SKILL_ASSEMBLED:   'book-open-text',
  AUTHORITY_APPLIED: 'shield-check',
  TRADEOFF_MADE:     'git-compare-arrows',
  GOAL_SETTLED:      'circle-check',
};

/* The dock: one icon per tool, so a slot is recognisable before you read it. */
const TOOL_ICON = {
  check_grill:'flame', check_pantry:'refrigerator', check_wallet:'wallet',
  check_hardware_store:'door-open', check_weather:'cloud-sun',
  find_tool:'wrench', web_search:'search', set_thermostat:'thermometer',
  '__yard-work':'sprout',
};

const LEDGER_ICON = {
  grievances:'message-square-quote', lessons:'book-open-text',
  rulings:'scroll-text', people:'users-round',
  usage:'activity', outcomes:'clipboard-list',
};