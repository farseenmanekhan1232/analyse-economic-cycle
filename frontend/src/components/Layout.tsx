import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home', end: true },
  { to: '/positions', label: 'Positions' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/sips', label: 'SIPs' },
  { to: '/review', label: 'Review' },
  { to: '/groww', label: 'Groww' },
  { to: '/cycle', label: 'Cycle lab' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="side-nav">
        <div className="brand">
          <span className="brand-mark">Pulse OS</span>
          <span className="brand-sub">Investment operating system</span>
        </div>
        <nav>
          <ul className="nav-list">
            {links.map((l) => (
              <li key={l.to}>
                <NavLink
                  to={l.to}
                  end={l.end}
                  className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                >
                  {l.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="nav-foot">Cycle approximate. Positions precise.</div>
      </aside>
      <main className="main">
        <div className="page">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
