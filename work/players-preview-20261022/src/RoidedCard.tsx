import type {Dictionaries, Profile} from './App';
import {Portrait, type Visual} from './experience';
import type {RecapRoided} from '../lib/recaps';
import './roided.css';

const gameTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
});

function buildSlots(values: (number | null)[] | undefined, entries: Dictionaries['augments']) {
  return (values ?? []).flatMap((id, slot) => {
    if (!id || id < 0) return [];
    const entry = entries[String(id)];
    return [{
      slot,
      name: entry?.name,
      icon: entry?.icon_url?.startsWith('/assets/') ? entry.icon_url : undefined,
      rarity: entry?.rarity,
    }];
  });
}

export type RoidedEntry = {row: RecapRoided; profile: Profile; visual?: Visual};

type Props = {
  entries: RoidedEntry[];
  dictionary: Dictionaries;
  onOpen: (profileId: string) => void;
};

export default function RoidedCard({entries, dictionary, onOpen}: Props) {
  if (!entries.length) return null;
  return <section className="roided-panel" aria-labelledby="roided-heading">
    <div className="roided-heading">
      <h3 id="roided-heading">本周最胡 <span className="roided-topn">TOP {entries.length}</span></h3>
      <span className="roided-range">北京时间周一至今</span>
    </div>
    <ol className="roided-list">
      {entries.map(({row, profile, visual}, index) => {
        const hero = dictionary.champions[String(row.champion_id)]?.name || row.champion_name;
        const share = typeof row.damage_share === 'number' && Number.isFinite(row.damage_share)
          ? (row.damage_share * 100).toFixed(1) + '%' : null;
        const kda = row.kills != null && row.deaths != null && row.assists != null
          ? row.kills + ' / ' + row.deaths + ' / ' + row.assists : null;
        const augments = index === 0 ? buildSlots(row.augments, dictionary.augments) : [];
        return <li className="roided-entry" key={row.match_id || `${row.profile_id}-${row.started_ms}`} data-rank={index + 1}>
          <div className="roided-entry-head">
            <span className="roided-rank" aria-label={`第 ${index + 1} 名`}>{index + 1}</span>
            <button type="button" className="roided-player" onClick={() => onOpen(profile.id)} aria-label={'打开 ' + profile.name + ' 的玩家档案'}>
              <Portrait profile={profile} visual={visual}/>
              <span className="roided-player-info">
                <strong>{profile.name} <span aria-hidden="true">↗</span></strong>
                {hero && <span>{hero}</span>}
              </span>
            </button>
            {typeof row.win === 'boolean' && <span className="roided-result" data-win={row.win}>{row.win ? '胜' : '负'}</span>}
          </div>
          <dl className="roided-metrics">
            {share && <div className="roided-share"><dt>全队伤害占比</dt><dd>{share}</dd></div>}
            {row.damage != null && <div><dt>单局伤害</dt><dd>{row.damage.toLocaleString('zh-CN')}</dd></div>}
            {kda && <div><dt>K / D / A</dt><dd>{kda}</dd></div>}
          </dl>
          <div className="roided-meta">
            {row.started_ms != null && <time dateTime={new Date(row.started_ms).toISOString()}>{gameTime.format(row.started_ms)}</time>}
          </div>
          {!!augments.length && <div className="roided-build">
            <h4>本局海克斯</h4>
            <ul className="roided-augments" aria-label="本局海克斯">
              {augments.map(hex => <li key={hex.slot} data-rarity={hex.rarity}>
                {hex.icon ? <img src={hex.icon} alt="" loading="lazy"/> : <span className="roided-augment-icon" aria-hidden="true">⬡</span>}
                <span>{hex.name || '未知海克斯'}</span>
              </li>)}
            </ul>
          </div>}
        </li>;
      })}
    </ol>
    <p className="roided-foot">北京时间周一至今 · 单局全队伤害占比前三，不作实力排名</p>
  </section>;
}
