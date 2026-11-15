/// <reference types="vite/client" />

import { useState, type CSSProperties, type ReactNode } from 'react';
import desktopArt from './media/blg-championship.webp';
import mobileArt from './media/blg-championship-mobile.webp';
import './championship.css';

const activityDates = '11 月 16 日–22 日';
const activityTitle = '所有战绩海斗分额外翻倍';
const series = [
  { game: 1, winner: 'GEN' },
  { game: 2, winner: 'BLG' },
  { game: 3, winner: 'BLG' },
  { game: 4, winner: 'BLG' },
];

export function ChampionshipHero({ children }: { children: ReactNode }) {
  const [burst, setBurst] = useState(0);

  return (
    <div className="championship-feature">
      <section className="championship-hero" aria-labelledby="championship-title">
        <picture className="championship-picture">
          <source media="(max-width: 740px)" srcSet={mobileArt} />
          <img src={desktopArt} width="1672" height="941" alt="" fetchPriority="high" />
        </picture>
        <div className="championship-copy">
          <p className="championship-kicker">2026 英雄联盟全球总决赛</p>
          <h1 id="championship-title"><span>BLG</span>我们是冠军！</h1>
          <div className="championship-result" aria-label="决赛比分，BLG 三比一战胜 GEN">
            <b>BLG</b><strong>3<span>:</span>1</strong><b>GEN</b>
          </div>
          <ol className="championship-series" aria-label="决赛各局胜者">
            {series.map(({ game, winner }) => (
              <li key={game} data-winner={winner} aria-label={`第 ${game} 局，${winner} 获胜`}>
                <span>G{game}</span> {winner}
              </li>
            ))}
          </ol>
          <div className="championship-actions">
            {children}
            <a href="#championship-week">夺冠周活动 <span aria-hidden="true">↓</span></a>
          </div>
        </div>
        <button className="championship-celebrate" type="button" onClick={() => setBurst(value => value + 1)}>
          <span aria-hidden="true">✦</span> 放礼花
        </button>
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
