import React from 'react';
import {createRoot} from 'react-dom/client';
import VersionIntel from './VersionIntel';
import { ChampionshipRibbon } from './Championship';
import {track, trackSession} from '../lib/analytics';
import './base.css';
import './version-intel.css';

track('page_view', {detail: JSON.stringify({entry: 'intel'})});
trackSession();

createRoot(document.getElementById('root')!).render(<React.StrictMode><div className="championship-intel"><div className="site-shell"><ChampionshipRibbon /></div><VersionIntel/></div></React.StrictMode>);
