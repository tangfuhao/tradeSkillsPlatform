import { NavLink, Outlet } from 'react-router-dom';

function ProductNavLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink className={({ isActive }) => `workbench-nav-link${isActive ? ' is-active' : ''}`} to={to}>
      {label}
    </NavLink>
  );
}

export default function ProductLayout() {
  return (
    <div className="workbench-shell">
      <div className="workbench-backdrop" />
      <header className="workbench-topbar">
        <div className="workbench-brand-block">
          <p className="brand-kicker">TradeSkills Workbench</p>
          <strong className="brand-title">Strategy Operations Desk</strong>
          <span className="brand-note">Immutable strategies · many backtests · one live runtime</span>
        </div>
        <nav aria-label="Primary" className="workbench-nav">
          <ProductNavLink to="/" label="概览" />
          <ProductNavLink to="/replays" label="回测" />
          <ProductNavLink to="/signals" label="实时" />
          <ProductNavLink to="/strategies" label="策略" />
          <ProductNavLink to="/console" label="Console" />
        </nav>
      </header>
      <main className="workbench-main">
        <Outlet />
      </main>
    </div>
  );
}
