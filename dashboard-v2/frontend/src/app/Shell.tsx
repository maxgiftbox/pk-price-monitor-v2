import { useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { trackDashboardAccess } from '../lib/accessAnalytics';

const navClass = ({ isActive }: { isActive: boolean }) => `nav-link ${isActive ? 'active' : ''}`;

export function Shell() {
  const location = useLocation();

  useEffect(() => {
    trackDashboardAccess(location.pathname);
  }, [location.pathname]);

  useEffect(() => {
    const trackWhenActive = () => {
      if (document.visibilityState === 'visible') {
        trackDashboardAccess(location.pathname);
      }
    };

    window.addEventListener('focus', trackWhenActive);
    document.addEventListener('visibilitychange', trackWhenActive);
    return () => {
      window.removeEventListener('focus', trackWhenActive);
      document.removeEventListener('visibilitychange', trackWhenActive);
    };
  }, [location.pathname]);

  return <div className="app-shell">
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand-mark"><span>Daraz</span><strong>EL Intelligence</strong></div>
        <nav>
          <NavLink className={navClass} to="/pricing">Pricing</NavLink>
          <NavLink className={navClass} to="/availability">Availability</NavLink>
          <NavLink className={navClass} to="/products">Product</NavLink>
          <NavLink className={navClass} to="/weekly-brief">Weekly Brief</NavLink>
          <NavLink className={navClass} to="/consumer-voice">Consumer Voice</NavLink>
          <NavLink className={navClass} to="/social-intelligence">Social Voice</NavLink>
        </nav>
        <div className="topbar-status"><i /> Dashboard loaded</div>
      </div>
    </header>
    <main className="main-content"><Outlet /></main>
  </div>;
}
