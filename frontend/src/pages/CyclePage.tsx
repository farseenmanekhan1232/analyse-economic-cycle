export function CyclePage() {
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Cycle lab</p>
          <h1 className="page-title">Research, demoted</h1>
          <p className="page-lead">
            Run Kite-backed cycle analysis here. Review open positions before acting on new scores.
          </p>
        </div>
      </header>

      <div className="banner">
        <span>
          You may have open satellite positions from prior runs. Review them on Home before acting on
          new scores.
        </span>
        <a className="btn btn-sm" href="/">
          Open book
        </a>
      </div>

      <section className="panel">
        <p className="panel-label">Legacy dashboard</p>
        <p className="muted">
          The full cycle dashboard (gauges, sector scores, fund picks) still runs on the FastAPI
          server.
        </p>
        <a className="btn" href="http://127.0.0.1:8000/dashboard" target="_blank" rel="noreferrer">
          Open cycle dashboard
        </a>
      </section>
    </>
  )
}
