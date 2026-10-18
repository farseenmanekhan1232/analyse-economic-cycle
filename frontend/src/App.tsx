/**
 * Legacy Vite Pulse OS (SIP / satellite / review) is retired.
 * Primary product: Next.js Decision OS at http://127.0.0.1:3000
 */
export default function App() {
  if (typeof window !== 'undefined') {
    window.location.replace('http://127.0.0.1:3000/analyse')
  }
  return (
    <div style={{ fontFamily: 'system-ui', padding: 48, maxWidth: 480 }}>
      <h1>Pulse Decision OS moved</h1>
      <p>
        Analyse / Holdings / Sync now live at{' '}
        <a href="http://127.0.0.1:3000/analyse">http://127.0.0.1:3000</a>.
      </p>
      <p style={{ color: '#666', fontSize: 14 }}>
        SIP registry, satellite budget, and monthly review wizard are no longer the primary UX.
      </p>
    </div>
  )
}
