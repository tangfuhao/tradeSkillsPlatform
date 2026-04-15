import { NavLink, Outlet } from 'react-router-dom';

function ProductNavLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink className={({ isActive }) => `product-nav-link${isActive ? ' is-active' : ''}`} to={to}>
      {label}
    </NavLink>
  );
}

export default function ProductLayout() {
  return (
    <div className="product-app-shell">
      <div className="product-background-glow product-background-glow-left" />
      <div className="product-background-glow product-background-glow-right" />
      <div className="rain-grid" />
      <header className="product-topbar">
        <div>
          <p className="product-kicker">TradeSkills / Neon Noir</p>
          <strong className="product-brand">Agent Trading Theater</strong>
        </div>
        <nav className="product-nav" aria-label="Primary">
          <ProductNavLink to="/" label="Home" />
          <ProductNavLink to="/replays" label="Replay Theater" />
          <ProductNavLink to="/signals" label="Signals" />
          <ProductNavLink to="/strategies" label="Strategies" />
          <ProductNavLink to="/console" label="Console" />
        </nav>
      </header>
      <main className="product-main">
        <Outlet />
      </main>
    </div>
  );
}
