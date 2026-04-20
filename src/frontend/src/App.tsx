import { Button } from "@/components/ui/button"
import { CheckCircle, Upload, MessageSquare, Key } from "lucide-react"

function App() {
  const handleTestBackend = async () => {
    try {
      // Hardcode the API URL for testing
      const apiBaseUrl = 'http://localhost/api'
      console.log('Testing backend connection to:', `${apiBaseUrl}/health/`)
      const response = await fetch(`${apiBaseUrl}/health/`)
      console.log('Response status:', response.status, response.statusText)
      const data = await response.json()
      alert(`Backend Health: ${data.status}\nTimestamp: ${data.timestamp}`)
    } catch (error) {
      console.error('Error connecting to backend:', error)
      alert(`Error connecting to backend: ${error}`)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 to-purple-700 flex items-center justify-center p-4">
      <div className="w-full max-w-4xl bg-white rounded-2xl shadow-2xl overflow-hidden">
        <header className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-8 text-center">
          <h1 className="text-4xl font-bold mb-2">DocuChat Frontend</h1>
          <p className="text-xl opacity-90">Vite + React + TypeScript + TailwindCSS + shadcn/ui</p>
        </header>
        <main className="p-8">
          <div className="bg-gray-50 rounded-xl p-6 mb-6 border-l-4 border-green-500">
            <h2 className="text-2xl font-semibold text-gray-800 mb-4">Frontend Service Status</h2>
            <div className="space-y-3">
              <div className="bg-white p-4 rounded-lg border border-gray-200 flex items-center justify-between">
                <div>
                  <span className="text-green-600 font-bold flex items-center">
                    <CheckCircle className="mr-2 h-5 w-5" />
                    ✅ Running on port 5173
                  </span>
                </div>
                <Button onClick={handleTestBackend} variant="outline" size="sm">
                  Test Backend Connection
                </Button>
              </div>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <p className="text-gray-700">
                  Hot reload: <span className="text-blue-600 font-medium">Enabled</span>
                </p>
              </div>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <p className="text-gray-700">
                  API Base URL: <code className="bg-gray-100 px-2 py-1 rounded text-sm font-mono ml-2">
                    {import.meta.env.VITE_API_BASE_URL || 'http://localhost/api'}
                  </code>
                </p>
              </div>
            </div>
          </div>
          <div className="bg-blue-50 rounded-xl p-6 border-l-4 border-blue-500">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">Next Steps:</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <div className="flex items-center mb-2">
                  <Key className="h-5 w-5 text-blue-600 mr-2" />
                  <h4 className="font-semibold">Authentication UI</h4>
                </div>
                <p className="text-sm text-gray-600">Login, registration, and JWT token management</p>
              </div>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <div className="flex items-center mb-2">
                  <Upload className="h-5 w-5 text-blue-600 mr-2" />
                  <h4 className="font-semibold">Document Upload</h4>
                </div>
                <p className="text-sm text-gray-600">PDF upload with progress tracking</p>
              </div>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <div className="flex items-center mb-2">
                  <MessageSquare className="h-5 w-5 text-blue-600 mr-2" />
                  <h4 className="font-semibold">Chat Interface</h4>
                </div>
                <p className="text-sm text-gray-600">Real-time conversation with documents</p>
              </div>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
                <div className="flex items-center mb-2">
                  <CheckCircle className="h-5 w-5 text-blue-600 mr-2" />
                  <h4 className="font-semibold">API Integration</h4>
                </div>
                <p className="text-sm text-gray-600">Connect to backend REST API</p>
              </div>
            </div>
            <div className="mt-6 flex gap-3">
              <Button className="flex-1">Get Started</Button>
              <Button variant="outline" className="flex-1">View Documentation</Button>
            </div>
          </div>
        </main>
        <footer className="bg-gray-800 text-white text-center p-4 text-sm opacity-80">
          <p>DocuChat RAG System - Epic E01: Project Scaffolding & DevOps</p>
          <p className="mt-1 text-xs opacity-60">Frontend initialized with shadcn/ui components</p>
        </footer>
      </div>
    </div>
  )
}

export default App