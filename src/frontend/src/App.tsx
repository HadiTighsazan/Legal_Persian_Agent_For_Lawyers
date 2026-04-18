function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>DocuChat Frontend</h1>
        <p>Vite + React + TypeScript</p>
      </header>
      <main className="app-main">
        <div className="status-card">
          <h2>Frontend Service Status</h2>
          <p className="status status-running">✅ Running on port 5173</p>
          <p className="status">Hot reload: Enabled</p>
          <p className="status">API Base URL: {import.meta.env.VITE_API_BASE_URL || 'http://localhost/api'}</p>
        </div>
        <div className="instructions">
          <h3>Next Steps:</h3>
          <ul>
            <li>Connect to backend API via Nginx proxy</li>
            <li>Implement authentication UI</li>
            <li>Build document upload interface</li>
            <li>Create chat interface</li>
          </ul>
        </div>
      </main>
      <footer className="app-footer">
        <p>DocuChat RAG System - Epic E01: Project Scaffolding & DevOps</p>
      </footer>
    </div>
  )
}

export default App