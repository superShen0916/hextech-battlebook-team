/// <reference types="vite/client" />

import { useState, type CSSProperties, type ReactNode } from 'react';
import desktopArt from './media/blg-championship.webp';
import mobileArt from './media/blg-championship-mobile.webp';
import './championship.css';

const activityDates = '11 月 16 日–22 日';
const activityTitle = '所有战绩海斗分额外翻倍';
const posterSource = 'https://x.com/BilibiliGaming/status/2121764046714360169/photo/2';
const boxScoreSource = 'https://gazette.statchk.gg/worlds/2026-11-14/blg-gen';
const bracketSource = 'https://lolesports.com/en-US/tournament/115660540725177488/stage/115660540725570707';

// Leaguepedia box scores via The Piltover Gazette. All figures are BLG–GEN.
const series = [
  { game: 1, winner: 'GEN', duration: '38:59', kills: '4–19', towers: '3–9', barons: '0–3' },
  { game: 2, winner: 'BLG', duration: '53:16', kills: '19–14', towers: '11–4', barons: '3–1' },
  { game: 3, winner: 'BLG', duration: '37:40', kills: '20–8', towers: '10–4', barons: '1–0' },
  { game: 4, winner: 'BLG', duration: '42:58', kills: '21–11', towers: '10–5', barons: '2–1' },
] as const;

export function ChampionshipPoster() {
  return (
    <figure className="championship-art">
      <picture>
        <source media="(max-width: 740px)" srcSet={mobileArt} />
        <img src={desktopArt} width="1920" height="1072" alt="BLG 选手身穿队服合影，海报写着「我们是冠军！」" fetchPriority="high" />
      </picture>
      <figcaption><a href={posterSource} target="_blank" rel="noreferrer">BLG 俱乐部官方冠军海报 ↗</a></figcaption>
    </figure>
  );
}

export function ChampionshipHero({ children }: { children: ReactNode }) {
  const [burst, setBurst] = useState(0);

  return (
    <div className="championship-feature">
      <section className="championship-hero" aria-labelledby="championship-title">
        <div className="championship-summary">
          <div>
            <p className="championship-kicker">2026 英雄联盟全球总决赛</p>
            <h1 className="championship-result" id="championship-title" aria-label="决赛比分，BLG 三比一战胜 GEN">
              <b>BLG</b><strong>3<span>:</span>1</strong><b>GEN</b>
            </h1>
          </div>
          <div className="championship-actions">
            {children}
            <a href="#championship-week">夺冠周活动 <span aria-hidden="true">↓</span></a>
            <button className="championship-celebrate" type="button" onClick={() => setBurst(value => value + 1)}>
              <span aria-hidden="true">✦</span> 放礼花
            </button>
          </div>
        </div>
        {burst > 0 && (
          <div className="championship-confetti" aria-hidden="true" key={burst}>
            {Array.from({ length: 30 }, (_, i) => (
              <i key={i} style={{
                '--x': `${((i * 137) % 97) - 48}cqw`,
                '--y': `-${90 + (i * 37) % 330}px`,
                '--spin': `${240 + i * 71}deg`,
                '--delay': `${(i % 7) * 22}ms`,
              } as CSSProperties} />
            ))}
          </div>
        )}
      </section>
      <section className="championship-games" aria-labelledby="championship-games-title">
        <header>
          <h2 id="championship-games-title">决赛逐局战绩</h2>
          <span>数据顺序 BLG – GEN</span>
        </header>
        <ol className="championship-series">
          {series.map(({ game, winner, duration, kills, towers, barons }) => (
            <li key={game} data-winner={winner}>
              <div className="championship-game-heading">
                <h3>第 {game} 局</h3><span>{winner} 胜</span>
              </div>
              <dl>
                <div><dt>时长</dt><dd>{duration}</dd></div>
                <div><dt>击杀</dt><dd>{kills}</dd></div>
                <div><dt>推塔</dt><dd>{towers}</dd></div>
                <div><dt>大龙</dt><dd>{barons}</dd></div>
              </dl>
              <a href={`${boxScoreSource}/${game}`} target="_blank" rel="noreferrer" aria-label={`第 ${game} 局详细数据与录像`}>详情与录像 ↗</a>
            </li>
          ))}
        </ol>
        <p className="championship-data-note">
          <a href={bracketSource} target="_blank" rel="noreferrer">LoL Esports 官方赛果 ↗</a>
          <span>逐局数据来自 Leaguepedia，经 The Piltover Gazette 展示</span>
        </p>
      </section>
      <section className="championship-event" id="championship-week" aria-labelledby="championship-event-title">
        <div className="championship-multiplier" aria-hidden="true">×2</div>
        <div className="championship-event-copy">
          <p>BLG 夺冠周预告</p>
          <h2 id="championship-event-title">{activityTitle}</h2>
        </div>
        <p className="championship-dates"><strong>{activityDates}</strong><span>2026 · 北京时间</span></p>
      </section>
    </div>
  );
}

export function ChampionshipRibbon() {
  return (
    <aside className="championship-ribbon" aria-label="BLG 夺冠活动">
      <strong><span aria-hidden="true">✦</span> BLG 世界冠军</strong>
      <span>{activityDates} · {activityTitle}</span>
    </aside>
  );
}
