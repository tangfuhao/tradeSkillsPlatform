import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { BookMarked, FlaskConical, LayoutDashboard, Menu, Plus, Radio, Terminal, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import NewStrategyDrawer from '../components/NewStrategyDrawer';

type NavItem = { to: string; label: string; Icon: LucideIcon };

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '概览', Icon: LayoutDashboard },
  { to: '/replays', label: '回测', Icon: FlaskConical },
  { to: '/signals', label: '实时', Icon: Radio },
  { to: '/strategies', label: '策略', Icon: BookMarked },
  { to: '/console', label: '控制台', Icon: Terminal },
];

function ProductNavLink({ to, label, Icon }: NavItem) {
  return (
    <NavLink
      className={({ isActive }) => `workbench-nav-link${isActive ? ' is-active' : ''}`}
      end={to === '/'}
      to={to}
    >
      <Icon size={15} />
      {label}
    </NavLink>
  );
}

export default function ProductLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="workbench-shell">
      <div className="workbench-backdrop" />
      <header className="workbench-topbar">
        <NavLink className="workbench-wordmark" to="/">TradeSkills</NavLink>

        <button
          aria-label="菜单"
          className="mobile-nav-toggle"
          onClick={() => setMobileNavOpen(!mobileNavOpen)}
          type="button"
        >
          {mobileNavOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <nav
          aria-label="Primary"
          className={`workbench-nav${mobileNavOpen ? ' is-open' : ''}`}
        >
          {NAV_ITEMS.map((item) => (
            <ProductNavLink key={item.to} {...item} />
          ))}
        </nav>

        <div className="workbench-topbar-end">
          <button
            className="action-button is-primary"
            onClick={() => setDrawerOpen(true)}
            type="button"
          >
            <Plus size={15} />
            新建策略
          </button>
        </div>
      </header>
      <main className="workbench-main">
        <Outlet />
      </main>
      <NewStrategyDrawer open={drawerOpen} onOpenChange={setDrawerOpen} />
    </div>
  );
}
