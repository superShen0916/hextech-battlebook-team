import assert from 'node:assert/strict';
import fs from 'node:fs';
const app=fs.readFileSync('src/App.tsx','utf8'),lobby=fs.readFileSync('src/Lobby.tsx','utf8');
for(const id of ['overview','preferences','heroes','hextech','honors','companions','matches'])assert.ok(app.includes('id="'+id+'"'),'Lost section: '+id);
for(const award of ['best_partner','worst_partner','damage_carry','most_played','teamfighter','assist_master','protector','penta_king','mvp_star','kill_harvester'])assert.ok(app.includes('"'+award+'"'));
for(const feature of ['HeroCards','Holdings','PersonalBadges','QuickNav','MatchRoster'])assert.ok(app.includes(feature));
for(const feature of ['PairStudio','AchievementHall','RecapStudio'])assert.ok(lobby.includes(feature));
assert.ok(!/主号|站长账号|站点最初账号/.test(app+lobby));
console.log('PASS: seven original sections, ten honors, holdings, heroes, sharing, roster, equal player entries and new recaps.');
