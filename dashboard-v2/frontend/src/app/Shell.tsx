import { NavLink, Outlet } from 'react-router-dom';

const navClass = ({ isActive }: { isActive: boolean }) => `nav-link ${isActive ? 'active' : ''}`;

export function Shell() {
  return <div className="app-shell">
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand-mark"><span>Daraz</span><strong>EL Intelligence</strong></div>
        <nav>
          <NavLink className={navClass} to="/pricing">Pricing</NavLink>
          <NavLink className={navClass} to="/products">Product</NavLink>
          <NavLink className={navClass} to="/consumer-voice">Consumer Voice</NavLink>
        </nav>
        <div className="topbar-status"><i /> Dashboard loaded</div>
      </div>
    </header>
    <main className="main-content"><Outlet /></main>
  </div>;
}
