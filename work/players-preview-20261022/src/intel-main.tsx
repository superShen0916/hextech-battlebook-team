import React from 'react';
import {createRoot} from 'react-dom/client';
import VersionIntel from './VersionIntel';
import {track, trackSession} from '../lib/analytics';
import './base.css';
import './version-intel.css';

track('page_view', {detail: JSON.stringify({entry: 'intel'})});
trackSession();

createRoot(document.getElementById('root')!).render(<React.StrictMode><VersionIntel/></React.StrictMode>);
